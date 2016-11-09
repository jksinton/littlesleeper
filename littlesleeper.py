#!/usr/bin/python

#************************************************************************************
# Copyright (c) 2016 James Sinton
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#************************************************************************************
#   CHANGE LOG
#   2016-11-01  Initial creation and design framework                     - 0.1.0
#   2016-11-02  Read MP3 stream with a thread and queue the data          - 0.1.1
#   2016-11-07  Process stream buffer with a thread                       - 0.1.2
#
#************************************************************************************

import os
import urllib2
import audioread
import threading
import datetime
import time
import matplotlib # this must come before librosa

matplotlib.use('Agg')

import librosa
import matplotlib.pyplot as plt
import numpy as np
from multiprocessing.connection import Listener, Client
from scipy import ndimage, interpolate
from cStringIO import StringIO

import tornado.httpserver
import tornado.ioloop
import tornado.web
import tornado.websocket
import tornado.gen

try:
    import queue
except ImportError:
    import Queue as queue

# the sample rate of the audio parameter recovered from the 
# the audio stream and set in samples/seconds
SAMPLE_RATE = 2

# bit rate of the audio stream set in kbits/s
BIT_RATE = 112

# After the signal has been normalized to the range [0, 1], volumes higher than this will be
# classified as noise.
# Change this based on: background noise, how loud the baby is, etc.
NOISE_THRESHOLD = 0.25

# seconds of quiet before transition mode from "noise" to "quiet"
MIN_QUIET_TIME = 30

# seconds of noise before transition mode from "quiet" to "noise"
MIN_NOISE_TIME = 6

# local server address to send the results to the tornado web server
RESULTS_SERVER_ADDRESS = ('localhost', 6000)

# web server address and port to set tornado.httpserver.HTTPServer().listen()
WEB_SERVER_ADDRESS = ('0.0.0.0', 8090)

# Store the Websocket client objects in this array (do not change this one)
clients = []

class QueueAudioStreamReader(threading.Thread):
    """A thread that connects to an MP3 stream and sends the stream data
    to a FIFO queue called queue_buffer.
    """
    def __init__(self, url, blocksize=1024, discard=False): 
        super(QueueAudioStreamReader, self).__init__()
        self.url = url
        self.blocksize = blocksize
        self.daemon = False
        self.discard = discard
        self.queue_buffer = None if discard else queue.Queue()

    def run(self):
        print "Connecting to Icecast server\n"
        stream_data = urllib2.urlopen(self.url)
        print stream_data.info()
        # to do: parse streamData.info()
        while True:
            data = stream_data.read(self.blocksize)
            time_stamp = datetime.datetime.now()
            if not data:
                continue
            if not self.discard:
                self.queue_buffer.put((data, time_stamp))
                self.queue_buffer.task_done()

def StreamBufferReader(queue_read, timeout=30.0): # todo: implement a timeout for this queue
    """An iterator generator that reads the stream buffer and 
    yields the compressed audio data and the time stamp
    """
    while True:
        if not queue_read.empty():
            data = None
            data, time_stamp = queue_read.get()
            if data:
                yield data, time_stamp
            else:
                continue

def format_time_difference(time1, time2):
    """Return the time difference as a formated str
    """
    time_diff = datetime.datetime.fromtimestamp(time2) - datetime.datetime.fromtimestamp(time1)
    return str(time_diff).split('.')[0]

class ProcessAudioStreamBuffer(threading.Thread):
    """A thread that processes the MP3 stream data and 
    puts the analyzed results in a queue to be hosted by the results server
    """
    def __init__(self, queue_read, discard=False):
        super(ProcessAudioStreamBuffer, self).__init__()
        self.daemon = False
        self.discard = discard
        self.queue_read = queue_read
        self.results_buffer = None if discard else queue.Queue()

    def run(self):
        audio_dtype = np.float32
        onehour = 60 * 60
        buffer_period = onehour*12
        buffer_len = int(buffer_period*SAMPLE_RATE) # window of audio data in memory data for analysis
        default = np.float32(0.0) # default value if there is a decode failure
        pos = 0 # position within the buffer
        counter = 0 # counter for determining when to queue the results or do other repeated tasks
    
        # create data buffers for the audio and time stamps:
        # (1) set all the audio buffer elements zero
        # (2) set all time stamp elements to now
        time_stamps = np.empty(buffer_len, dtype=datetime.datetime)
        audio_buffer = np.zeros(buffer_len, dtype=audio_dtype)
        time_stamps[:] = datetime.datetime.fromtimestamp(time.time())
        
        print "Processing MP3 queue buffer\n"
        for mp3data, timestamp in StreamBufferReader(self.queue_read):
            signaldata = None
            try:
                signaldata = audioread.decode(StringIO(mp3data))
            except (audioread.NoBackendError, audioread.ffdec.ReadTimeoutError):
                print "Decode error. Setting default value"
            
            # convert the integer buffer to an array of np.float32 elementa
            # this portion is an excerpt from librosa.core.load()
            # https://github.com/librosa/librosa/blob/master/librosa/core/audio.py
            if signaldata is not None:
                signal = []
                for frame in signaldata:
                    frame = librosa.util.buf_to_float(frame)
                    #print len(frame)
                    signal.append(frame)

                if signal:
                    signal = np.concatenate(signal)
                
                # Final cleanup for dtype and contiguity
                signal = np.ascontiguousarray(signal, dtype=audio_dtype)
                
                peak =  np.abs(signal).max()
            # there was a decode failure, so set the peak value to 0.0
            else:
                peak = default
            # load the latest audio parameter and its time stamp in to the buffers
            time_stamps[pos] = timestamp
            audio_buffer[pos] = peak
            pos = (pos + 1) % buffer_len

            # roll the arrays so that the latest readings are at the end
            rolled_time_stamps = np.roll(time_stamps, shift=buffer_len-pos)
            rolled_audio_buffer = np.roll(audio_buffer, shift=buffer_len-pos)
            
            # apply some smoothing
            sigma = 4 * (SAMPLE_RATE)
            rolled_audio_buffer = ndimage.gaussian_filter1d(rolled_audio_buffer, 
                    sigma=sigma, mode="reflect")
            
            # get the last hour of data for the plot and re-sample to 1 value per second
            hour_chunks = int(onehour * SAMPLE_RATE)
            xs = np.arange(hour_chunks)
            f = interpolate.interp1d(xs, rolled_audio_buffer[-hour_chunks:])
            audio_plot = f(np.linspace(start=0, stop=xs[-1], num=3600)) 
            
            # ignore positions with no readings
            mask = rolled_audio_buffer > 0
            rolled_time_stamps = rolled_time_stamps[mask]
            rolled_audio_buffer = rolled_audio_buffer[mask]
            
            # partition the audio history into blocks of type:
            #   1. noise, where the volume is greater than noise_threshold
            #   2. silence, where the volume is less than noise_threshold
            noise = rolled_audio_buffer > NOISE_THRESHOLD
            silent = rolled_audio_buffer < NOISE_THRESHOLD

            # join "noise blocks" that are closer together than min_quiet_time
            crying_blocks = []
            if np.any(noise):
                silent_labels, _ = ndimage.label(silent)
                silent_ranges = ndimage.find_objects(silent_labels)
                for silent_block in silent_ranges:
                    start = silent_block[0].start
                    stop = silent_block[0].stop

                    # don't join silence blocks at the beginning or end
                    if start == 0:
                        continue
                    interval_length = time.mktime(rolled_time_stamps[stop-1].timetuple()) -  time.mktime(rolled_time_stamps[start].timetuple())
                    if interval_length < MIN_QUIET_TIME:
                        noise[start:stop] = True

                # find noise blocks start times and duration
                crying_labels, num_crying_blocks = ndimage.label(noise)
                crying_ranges = ndimage.find_objects(crying_labels)
                for cry in crying_ranges:
                    start = time.mktime(rolled_time_stamps[cry[0].start].timetuple())
                    stop = time.mktime(rolled_time_stamps[cry[0].stop-1].timetuple())
                    duration = stop - start

                    # ignore isolated noises (i.e. with a duration less than min_noise_time)
                    if duration < MIN_NOISE_TIME:
                        continue

                    # save some info about the noise block
                    crying_blocks.append({'start': start,
                                          'start_str': datetime.datetime.fromtimestamp(start).strftime("%I:%M:%S %p").lstrip('0'),
                                          'stop': stop,
                                          'duration': format_time_difference(start, stop)})

            # determine how long have we been in the current state
            time_current = time.time()
            time_crying = ""
            time_quiet = ""
            str_crying = "Baby noise for "
            str_quiet = "Baby quiet for "
            if len(crying_blocks) == 0:
                time_quiet = str_quiet + format_time_difference(time.mktime(rolled_time_stamps[0].timetuple()), 
                        time_current)
            else:
                if time_current - crying_blocks[-1]['stop'] < MIN_QUIET_TIME:
                    time_crying = str_crying + format_time_difference(crying_blocks[-1]['start'], time_current)
                else:
                    time_quiet = str_quiet + format_time_difference(crying_blocks[-1]['stop'], time_current)
            
            timestamp_str = timestamp.strftime("%H:%M:%S.%f")
             
            # generate a plot every 30 seconds and write the current state to the log file
            if counter is (SAMPLE_RATE*30)-1:
                print peak, "\t", timestamp_str
                # get the last hour of data for the plot (not implemented and re-sample to 1 value per second)
                hour_chunk = rolled_audio_buffer[-hour_chunks:]
                hour_timestamps = rolled_time_stamps[-hour_chunks:]
                
                #print "\nGenerating plot\n"
                # convert the time stamps to matplotlib format
                time_stamps_plt = matplotlib.dates.date2num(hour_timestamps)

                # generate plot of the past hour
                plt.figure()
                plt.plot_date(time_stamps_plt, hour_chunk, xdate=True, label='peak volumes',
                        linestyle='solid', marker=None)
                plt.gcf().autofmt_xdate()
                plt.legend(loc='best')
                plt.savefig('hour_window')
                plt.close()
                
                f = open('littlesleeper.log','w')
                f.write(time_crying + '\n')
                f.write(time_quiet + '\n')
                if len(crying_blocks):
                    f.write('Crying Blocks:\n')
                    for crying_block in crying_blocks:
                        f.write(crying_block['start_str'] +'\t'+ crying_block['duration']+'\n')
                f.close()
            
            # every second load the results in a queue that is read by ResultsServer
            if not self.discard:
                #print peak, "\t", timestamp_str
                if counter % (SAMPLE_RATE*1) is (SAMPLE_RATE*1)-1:
                    results = { 'audio_plot': audio_plot,
                                'crying_blocks': crying_blocks,
                                'time_crying': time_crying,
                                'time_quiet': time_quiet }
                    self.results_buffer.put(results)
                    self.results_buffer.task_done()
                    
            # incremenent counter 
            counter = (counter + 1) % (SAMPLE_RATE * 30)

class ResultsServer(threading.Thread):
    """A thread that hosts the results calculated by ProcessAudioStreamBuffer and sends the results
    to the tornado web server to post to the WebSocket client(s)
    """
    def __init__(self, results_buffer):
        super(ResultsServer, self).__init__()
        self.daemon = False
        self.results_buffer = results_buffer

    def run(self):
        listener = Listener(RESULTS_SERVER_ADDRESS)
        while True:
            conn = listener.accept()
            #print self.results_buffer.qsize()
            conn.send(self.results_buffer.get())
            conn.close()

# Web server classes:

class IndexHandler(tornado.web.RequestHandler):
    def get(self):
        self.render('www/index.html')

class WebSocketHandler(tornado.websocket.WebSocketHandler):
    def open(self):
        print "New connection"
        global clients
        clients.append(self)

    def on_close(self):
        print "Connection closed"
        global clients
        clients.remove(self)

def broadcast_results():
    """Every second get the results from the ResultsServer as defined by the scheduler and
    try to send the results to the Websocket client(s)
    """
    conn = Client(RESULTS_SERVER_ADDRESS)
    results = conn.recv()
    conn.close()
    # send results to all clients
    now = datetime.datetime.now()
    results['date_current'] = '{dt:%A} {dt:%B} {dt.day}, {dt.year}'.format(dt=now)
    results['time_current'] = now.strftime("%I:%M:%S %p").lstrip('0')
    results['audio_plot'] = results['audio_plot'].tolist()
    for c in clients:
        #print "\nSending results to WebSocket Client\n"
        c.write_message(results)

def start_webserver():
    settings = {
        "static_path": os.path.join(os.path.dirname(__file__), "www/static"),
    }
    app = tornado.web.Application(
        handlers=[
            (r"/", IndexHandler),
            (r"/ws", WebSocketHandler),
        ], **settings
    )
    http_server = tornado.httpserver.HTTPServer(app)
    http_server.listen(WEB_SERVER_ADDRESS[1], WEB_SERVER_ADDRESS[0])
    print "\nListening on port:", WEB_SERVER_ADDRESS[1], '\n'
 
    main_loop = tornado.ioloop.IOLoop.instance()
    scheduler = tornado.ioloop.PeriodicCallback(broadcast_results, 1000, io_loop=main_loop)
    scheduler.start()
    main_loop.start()    

def main():
    # bit rate in kb * kilo / one byte
    byte_rate = int(BIT_RATE*1024/float(8))
    sample_period = 1.0/SAMPLE_RATE
    blocksize = int(byte_rate*sample_period)
    url = "http://10.0.1.203:8000/raspi"
    
    # start thread to read MP3 data from Icecast server and 
    # put the data in queue_buffer
    mp3stream = QueueAudioStreamReader(url, blocksize=blocksize)
    mp3stream.start()
    
    # read the MP3 data in the queue, decode it, put it in the audio_buffer, and analyze it
    process_queue = ProcessAudioStreamBuffer(mp3stream.queue_buffer, discard=False)
    process_queue.start()
    
    # host results in the results_buffer and send them to the webserver 
    results_server = ResultsServer(process_queue.results_buffer)
    results_server.start()
    
    # start tornado web server and web socket
    start_webserver()

if __name__ == "__main__":
    main()
