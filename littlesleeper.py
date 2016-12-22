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
#   2016-11-01  Initial port of littlesleeper                             - 0.1.0
#   2016-11-02  Read MP3 stream with a thread and queue the data          - 0.1.1
#   2016-11-07  Process stream buffer with a thread                       - 0.1.2
#   2016-11-09  Host results on webserver                                 - 0.1.3
#   2016-11-12  Add command line arguments                                - 0.1.4
#   2016-11-15  Gracefully close threads and main process                 - 0.1.5
#               when SIGINT or SIGTERM signals are recieved
#   2016-11-30  Write hourly graphs for the entire buffer                 - 0.1.6
#   2016-12-22  config.py, password protected Icecast listener            - 0.1.7
#
#   TO-DOS:
#   (1) Store buffer in sqlite database
#   (2) Write hourly graphs for the entire buffer
#   (3) Analyze based on running average or a derivative
#   (4) Store mp3 audio if the threshold is reached
#   (5) Host html on apache/drupal and host websocket traffic in python/tornado
#   (6) Support python 2 and 3
#   (7) Error check command line arguments
#   (8) Fix 7-day buffer of crying block data
#
#************************************************************************************

import os
import argparse
import urllib2
import base64
import audioread
import threading
import datetime
import time
import signal
import sqlite3
import matplotlib # this must come before librosa

matplotlib.use('Agg')

import librosa
import matplotlib.pyplot as plt
import numpy as np
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

import config # change example.config.py to config.py

def SetupSqlDatabase(sql_db_file):
    db_conn = sqlite3.connect(sql_db_file)

    # create table(s)
    db_conn.close()


def GetCommandLineArgs():
    """Define command line arguments using argparse
    Return the arguments to main
    """
    version='0.1.7'
    parser = argparse.ArgumentParser(description='This monitors an MP3 stream.')
    parser.add_argument('-u','--stream-url',help='URL to the MP3 stream')
    parser.add_argument('-b','--bit-rate',help='bitrate of MP3 stream')
    parser.add_argument('-p','--web-port',help='port for the web server')
    parser.add_argument('-n','--noise-threshold',help='volume threshold, anything above is considered noise, anything below is considered silence')
    parser.add_argument('-v','--version',action='version', version='%(prog)s %(version)s' % {"prog": parser.prog, "version": version})
    parser.add_argument('-d','--debug',help='print debug messages',action="store_true")

    return parser.parse_args()
   

class QueueAudioStreamReader(threading.Thread):
    """A thread that connects to an MP3 stream and sends the stream data
    to a FIFO queue called queue_buffer.
    """
    def __init__(self, url, username, password, blocksize=1024, discard=False): 
        super(QueueAudioStreamReader, self).__init__()
        self.url = url
        self.username = username
        self.password = password
        self.blocksize = blocksize
        self.daemon = False
        self.discard = discard
        self.queue_buffer = None if discard else queue.Queue()
        self.StopThread = False

    def run(self):
        print "Connecting to Icecast server\n"
        request = urllib2.Request(self.url)
        base64string = base64.b64encode('%s:%s' % (self.username, self.password))
        request.add_header("Authorization", "Basic %s" % base64string) 
        #stream_data = urllib2.urlopen(self.url)
        stream_data = urllib2.urlopen(request)
        print stream_data.info()
        # todo: parse streamData.info()
        while True:
            data = stream_data.read(self.blocksize)
            time_stamp = datetime.datetime.now()
            if not data:
                continue
            if not self.discard:
                self.queue_buffer.put((data, time_stamp))
                self.queue_buffer.task_done()
            if self.StopThread:
                break
        stream_data.close()
    
    def stop(self):
        self.StopThread = True


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
    """Return the time difference as a formatted str
    """
    time_diff = datetime.datetime.fromtimestamp(time2) - datetime.datetime.fromtimestamp(time1)
    return str(time_diff).split('.')[0]


class ProcessAudioStreamBuffer(threading.Thread):
    """A thread that processes the MP3 stream data and 
    puts the analyzed results in a queue to be hosted by the results server
    """
    def __init__(self, queue_read, sample_rate, noise_threshold, min_quiet_time, min_noise_time, discard=False):
        super(ProcessAudioStreamBuffer, self).__init__()
        self.daemon = False
        self.discard = discard
        self.queue_read = queue_read
        self.sample_rate = sample_rate
        self.noise_threshold = noise_threshold
        self.min_quiet_time = min_quiet_time
        self.min_noise_time = min_noise_time
        self.results_buffer = None if discard else queue.Queue()
        self.StopThread = False

    def run(self):
        audio_dtype = np.float32
        secs_per_hour = 60 * 60
        hours_of_buffer = 12
        buffer_period = secs_per_hour*hours_of_buffer
        buffer_len = int(buffer_period*self.sample_rate) # window of audio data in memory data for analysis
        default = np.float32(0.0) # default value if there is a decode failure
        pos = 0 # position within the buffer
        counter = 0 # counter in for-loop to determine when to queue the results or do other repeated tasks
        

        # store crying blocks for a week
        crying_blocks = []

        ##########################################
        # to-do: store buffers in sqlite database
        ##########################################
        
        sqldb = 'ls.sqlite'


        # create data buffers for the audio and time stamps:
        # (1) set all the audio buffer elements zero
        # (2) set all time stamp elements to now
        time_stamps = np.empty(buffer_len, dtype=datetime.datetime)
        audio_buffer = np.zeros(buffer_len, dtype=audio_dtype)
        time_stamps[:] = datetime.datetime.fromtimestamp(time.time())
        
        print "Processing MP3 queue buffer\n"
        # this is essentially a while-true loop
        for mp3data, timestamp in StreamBufferReader(self.queue_read):
            signaldata = None
            timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")
            try:
                signaldata = audioread.decode(StringIO(mp3data))
            except (audioread.NoBackendError, audioread.ffdec.ReadTimeoutError):
                print timestamp_str,"\tDecode error. Setting default value."
            
            # convert the integer buffer to an array of np.float32 elements
            # this portion is an excerpt from librosa.core.load()
            # https://github.com/librosa/librosa/blob/master/librosa/core/audio.py
            if signaldata is not None:
                signal = []
                for frame in signaldata:
                    frame = librosa.util.buf_to_float(frame)
                    signal.append(frame)

                if signal:
                    signal = np.concatenate(signal)
                
                # Final cleanup for dtype and contiguity
                signal = np.ascontiguousarray(signal, dtype=audio_dtype)
                
                peak =  np.abs(signal).max()
            # there was a decode failure, so set the peak value to default value
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
            sigma = 4 * (self.sample_rate)
            rolled_audio_buffer = ndimage.gaussian_filter1d(rolled_audio_buffer, 
                    sigma=sigma, mode="reflect")
            
            # get the last hour of data for the plot and re-sample to 1 value per second
            hour_chunks = int(secs_per_hour * self.sample_rate)
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
            noise = rolled_audio_buffer > self.noise_threshold
            silent = rolled_audio_buffer < self.noise_threshold

            # join "noise blocks" that are closer together than min_quiet_time
            new_crying_blocks = []
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
                    if interval_length < self.min_quiet_time:
                        noise[start:stop] = True

                # find noise blocks start times and duration
                crying_labels, num_crying_blocks = ndimage.label(noise)
                crying_ranges = ndimage.find_objects(crying_labels)
                for cry in crying_ranges:
                    start = time.mktime(rolled_time_stamps[cry[0].start].timetuple())
                    stop = time.mktime(rolled_time_stamps[cry[0].stop-1].timetuple())
                    duration = stop - start
                    
                    # ignore isolated noises (i.e. with a duration less than min_noise_time)
                    if duration < self.min_noise_time:
                        continue

                    # save some info about the noise block
                    new_crying_blocks.append({  'start': start,
                                                'start_str': datetime.datetime.fromtimestamp(start).strftime("%Y-%m-%d  %I:%M:%S %p").lstrip('0'),
                                                'stop': stop,
                                                'duration': format_time_difference(start, stop) })
            
            
            # update crying blocks
            if len(new_crying_blocks) <= 1:
                crying_blocks = new_crying_blocks
            else:
                duration = new_crying_blocks[-1]['start'] - crying_blocks[0]['start']
                #print duration
                if duration < self.min_noise_time:
                    crying_blocks[0] = new_crying_blocks[-1]
                else: 
                    crying_blocks.append(new_crying_blocks[-1])
           
            # only keep the last 7 days worth of crying blocks
            # this is broken, it stores duplicates
            now = time.time()
            new_crying_blocks = []
            for crying_block in crying_blocks:
                if crying_block['start'] > (now - float(3600*24*7)):
                    new_crying_blocks.append(crying_block)
            crying_blocks = new_crying_blocks
            
            # sort crying blocks so that the most recent status is at the top
            crying_blocks = sorted(crying_blocks, key=lambda crying_block: crying_block['start'], reverse=True)
            
            # determine how long have we been in the current state
            time_current = time.time()
            time_crying = ""
            time_quiet = ""
            str_crying = "Baby noise for "
            str_quiet = "Baby quiet for "
            
            if len(new_crying_blocks) == 0:
                time_quiet = str_quiet + format_time_difference(time.mktime(rolled_time_stamps[0].timetuple()), 
                        time_current)
            else:
                # update status strings 
                if time_current - crying_blocks[0]['stop'] < self.min_quiet_time:
                    time_crying = str_crying + format_time_difference(crying_blocks[0]['start'], time_current)
                else:
                    time_quiet = str_quiet + format_time_difference(crying_blocks[0]['stop'], time_current)
            
            # every 30 seconds generate plots of the buffer and write the current state to the log file
            if counter is (self.sample_rate*30)-1:
                print timestamp_str, "\t", peak
                
                # reset the rolled buffers
                rolled_time_stamps = np.roll(time_stamps, shift=buffer_len-pos)
                rolled_audio_buffer = np.roll(audio_buffer, shift=buffer_len-pos)
                
                for i in range(hours_of_buffer):
                    # get the last hour of data for the plot 
                    start = hour_chunks*i
                    end = hour_chunks*(i+1)
                    hour_chunk = rolled_audio_buffer[start:end]
                    hour_timestamps = rolled_time_stamps[start:end]
                
                    # convert the time stamps to matplotlib format
                    time_stamps_plt = matplotlib.dates.date2num(hour_timestamps)

                    # generate plot of the past hour
                    plt.figure()
                    plt.plot_date(time_stamps_plt, hour_chunk, xdate=True, label='peak volume',
                            linestyle='solid', marker=None)
                    plt.gcf().autofmt_xdate()
                    plt.legend(loc='best')
                    plt.savefig('hour_window_' + str(hours_of_buffer - i))
                    plt.close()
                    
                f = open('littlesleeper.log','w')
                f.write(time_crying + '\n')
                f.write(time_quiet + '\n')
                if len(crying_blocks):
                    f.write('Crying Blocks:\n')
                    for crying_block in crying_blocks:
                        f.write(crying_block['start_str'] +'\t'+ crying_block['duration']+'\n')
                f.close()
            
            # every second load the results in a queue that is read by BroadcastResults
            if not self.discard:
                #print peak, "\t", timestamp_str
                if counter % (self.sample_rate*1) is (self.sample_rate*1)-1:
                    results = { 'audio_plot': audio_plot,
                                'crying_blocks': crying_blocks,
                                'time_crying': time_crying,
                                'time_quiet': time_quiet }
                    self.results_buffer.put(results)
                    self.results_buffer.task_done()
                    
            # incremenent counter 
            counter = (counter + 1) % (self.sample_rate * 30)
            
            if self.StopThread:
                break
        # cleanup here
        #
    
    def stop(self):
        self.StopThread = True


StopTornado = False

def SignalHandler(signum, frame, stream_thread=None, process_thread=None):
    print "closing"
    global StopTornado
    StopTornado = True
    stream_thread.stop()
    process_thread.stop()


# Web server classes:

clients = []

class IndexHandler(tornado.web.RequestHandler):
    def get(self):
        self.render('www/index.html')


class ResultsWebSocketHandler(tornado.websocket.WebSocketHandler):
    def check_origin(self, origin):
        return True
    
    def open(self):
        print "New connection"
        global clients
        clients.append(self)

    def on_close(self):
        print "Connection closed"
        global clients
        clients.remove(self)


def BroadcastResults(results_buffer):
    """Every second get the results from the ResultsServer as defined by the scheduler and
    try to send the results to the Websocket client(s)
    """
    results = results_buffer.get()
    # send results to all clients
    now = datetime.datetime.now()
    results['date_current'] = '{dt:%A} {dt:%B} {dt.day}, {dt.year}'.format(dt=now)
    results['time_current'] = now.strftime("%I:%M:%S %p").lstrip('0')
    results['audio_plot'] = results['audio_plot'].tolist()
    for c in clients:
        #print "\nSending results to WebSocket Client\n"
        c.write_message(results)


def TryExit():
    global StopTornado
    if StopTornado:
        # clean up here
        tornado.ioloop.IOLoop.instance().stop()

def main():
    args = GetCommandLineArgs()
    configDict = config.SetConf(args)
    
    # set config values
    bit_rate = configDict['BIT_RATE']
    sample_rate = configDict['SAMPLE_RATE']
    stream_url = configDict['STREAM_URL']
    username = configDict['USERNAME']
    password = configDict['PASSWORD']
    noise_threshold = configDict['NOISE_THRESHOLD']
    min_quiet_time = configDict['MIN_QUIET_TIME']
    min_noise_time = configDict['MIN_NOISE_TIME']
    web_server_address = configDict['WEB_SERVER_ADDRESS']

    # bit rate in kb * kilo / one byte
    byte_rate = int(bit_rate*1024/float(8))
    sample_period = 1.0/sample_rate
    blocksize = int(byte_rate*sample_period)
   
    # start thread to read MP3 data from Icecast server and 
    # put the data in queue_buffer
    mp3stream = QueueAudioStreamReader(stream_url, username, password, blocksize=blocksize)
    mp3stream.start()
    
    # Process the audio stream buffer:
    # (1) Decode each compressed audio block for the sample period
    # (2) Put a parameter indicative of the volume level for each block into a rolling buffer
    # (3) Determine the current status
    # (4) Find the noise blocks above the noise threshold
    # (5) Put the results in a queue called results_buffer
    process_queue = ProcessAudioStreamBuffer(mp3stream.queue_buffer, sample_rate, 
            noise_threshold, min_quiet_time, min_noise_time, discard=False)
    process_queue.start()

    # Start tornado web server and web socket hanlder
    settings = {
        "static_path": os.path.join(os.path.dirname(__file__), "www/static"),
    }
    app = tornado.web.Application(
        handlers=[
            tornado.web.url(r"/", IndexHandler),
            tornado.web.url(r"/ws", ResultsWebSocketHandler, name="ws"),
        ], **settings
    )
    http_server = tornado.httpserver.HTTPServer(app)
    http_server.listen(web_server_address[1], web_server_address[0])
    print "\nListening on port:", web_server_address[1], '\n'
 
    main_loop = tornado.ioloop.IOLoop.instance()
    scheduler = tornado.ioloop.PeriodicCallback(lambda: BroadcastResults(process_queue.results_buffer), 1000, io_loop=main_loop)
    try_exit = tornado.ioloop.PeriodicCallback(TryExit, 100, io_loop=main_loop)
    
    signal.signal(signal.SIGINT, lambda signum, frame: SignalHandler(signum, frame, stream_thread=mp3stream, process_thread=process_queue))
    signal.signal(signal.SIGTERM, lambda signum, frame: SignalHandler(signum, frame, stream_thread=mp3stream, process_thread=process_queue))
    
    scheduler.start()
    try_exit.start()
    main_loop.start()    

if __name__ == "__main__":
    main()
