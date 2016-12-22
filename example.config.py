#!/usr/bin/python

def SetConf(args):
    """Set the default values or the values received from the command line
    """
    # the sample rate of the audio parameter recovered from 
    # the audio stream and set in samples/seconds
    SAMPLE_RATE = 2

    # url to MP3 stream
    STREAM_URL = "http://localhost:8000/mountpoint"
   
    # Icecast authorized listener
    USERNAME = "user"
    
    # Icecast password for authorized listener
    PASSWORD = "hackme"

    # bit rate of the audio stream set in kbits/s
    BIT_RATE = 112

    # After the signal has been normalized to the range [0, 1], volumes higher than this will be
    # classified as noise.
    # Change this based on: background noise, how loud the baby is, etc.
    NOISE_THRESHOLD = 0.10

    # seconds of quiet before transition mode from "noise" to "quiet"
    MIN_QUIET_TIME = 30

    # seconds of noise before transition mode from "quiet" to "noise"
    MIN_NOISE_TIME = 6

    # web server address and port to set tornado.httpserver.HTTPServer().listen()
    WEB_SERVER_ADDRESS = ('0.0.0.0', 8090)
    
    # sqlite database filename
    SQLITE_FILE = 'ls.sqlite'

    # check the command line arguments for errors
    if args.stream_url:
        STREAM_URL = args.stream_url
    if args.bit_rate:
        BIT_RATE = int(args.bit_rate)
    if args.web_port:
        WEB_SERVER_ADDRESS[1] = args.web_port
    if args.noise_threshold:
        NOISE_THRESHOLD = float(args.noise_threshold)
    # set debug flag
    
    configDict = {  "SAMPLE_RATE":SAMPLE_RATE,
                    "STREAM_URL":STREAM_URL,
                    "USERNAME":USERNAME,
                    "PASSWORD":PASSWORD,
                    "BIT_RATE":BIT_RATE,
                    "NOISE_THRESHOLD":NOISE_THRESHOLD,
                    "MIN_QUIET_TIME":MIN_QUIET_TIME,
                    "MIN_NOISE_TIME":MIN_NOISE_TIME,
                    "WEB_SERVER_ADDRESS":WEB_SERVER_ADDRESS,
                    "SQLITE_FILE":SQLITE_FILE,
                 }

    return configDict
