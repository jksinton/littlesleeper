# littlesleeper2

This is a port of the noise monitor written by Neil Yager called [LittleSleeper](https://github.com/NeilYager/LittleSleeper). Many kudos to Neil for writing this.

The main difference between LittleSleeper2 and Neil's is that instead of reading the audio directly from the mic, it processes the audio data from an MP3 stream hosted by a RPi.

This allows the processing and web hosting to be handled completely by the RPi or offloaded to another computer that has a python environment. I've implemented the latter.

The architecure is shown below:
![alt text](https://github.com/jksinton/littlesleeper2/blob/master/common/ls2arch.png "Architecture")

The RPi can be the Icecast + Darkice server with a mic and Littlesleeper2 can run on any commputer with python.

## Required Python libraries:
* [matplotlib](http://matplotlib.org/)
* [numpy](http://www.numpy.org/)
* [scipy](https://www.scipy.org/)
* [tornado](http://www.tornadoweb.org/en/stable/)
* [librosa](http://librosa.github.io/librosa/)
* [audioread](https://github.com/beetbox/audioread) (branch/master that supports audioread.decode()) See [this issue](https://github.com/beetbox/audioread/issues/35)

## Other dependencies:
* You will also need to have FFMPEG installed to decode the audio stream.
