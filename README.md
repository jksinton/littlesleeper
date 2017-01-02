# littlesleeper2

Littlesleeper is an MP3 stream noise level monitor. It can be used as a baby crying monitor. It identifies crying blocks based on the peak volume that exceeds a threshold volume level and when that peak volume is present for a pre-set amount of time. These variables can be set in the configuration file `config.ini`.

This is a port of the noise monitor written by Neil Yager called [LittleSleeper](https://github.com/NeilYager/LittleSleeper). Many kudos to Neil for writing this.

The main difference between LittleSleeper2 and Neil's is that instead of reading the audio directly from a microphone, Littlesleeper2 processes the audio data from an MP3 stream hosted by a Raspbery Pi.

This allows the processing and web hosting to be handled completely by the RPi or offloaded to another computer that has a python environment. I primarily use the latter, so I can offload the processing to another server. However, I have briefly tested Littlesleeper2 on the Raspberry Pi and it seemed to outperform my Ubuntu Server based on CPU load.

The architecure is shown below:

![alt text](https://github.com/jksinton/littlesleeper2/blob/master/common/ls2arch.png "Architecture")

The RPi can be the Icecast + Darkice server with a mic and Littlesleeper2 can run on any commputer with python.

## Required Python libraries:
* [matplotlib](http://matplotlib.org/)
* [numpy](http://www.numpy.org/)
* [scipy](https://www.scipy.org/)
* [tornado](http://www.tornadoweb.org/en/stable/)
* [librosa](http://librosa.github.io/librosa/)
* [sqlalchemy](http://www.sqlalchemy.org/)
* [audioread](https://github.com/beetbox/audioread) (branch/master that supports audioread.decode()) See [this issue](https://github.com/beetbox/audioread/issues/35)

## Other dependencies:
* You will also need to have FFMPEG installed to decode the audio stream.

## Installation:
1. Setup Icecast + Darkice on Raspberry Pi
2. Set variables in `config.ini` and `www/static/config.js`:
  * For `config.ini`:
    * Copy `example.config.ini` to `config.ini`
    * Set the url to the MP3 stream with `STREAM_URL`
    * Set the port for the Tornado web server with `WEB_SERVER_PORT`
    * Set the bit rate of the MP3 stream with `BIT_RATE`. This is necessary to calculate the block of bytes read from the stream based on the `SAMPLE_RATE`.
    * Other variables, such as `NOISE_THRESHOLD`, `MIN_QUIET_TIME`, and `MIN_NOISE_TIME`, can be set based on your preferences.
  * For `www/static/config.js`:
    * Copy `www/static/example.config.js` to `www/static/config.js` 
    * Set the url to the Web Socket server with `ws_server` 
    * `ws_server` should be the LAN/WAN IP or FQDN of the Tornado Web Server and port set with `WEB_SERVER_PORT`
3. Run Littlesleeper2: `./littlesleeper.py`

## Other Features:
Littlesleeper can connect to an authenticated Icecast stream. However, the username and password are stored as ASCII in the `config.ini`.
