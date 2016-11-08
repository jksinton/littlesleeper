# littlesleeper2

This is a port of the noise monitor written by Neil Yager called [LittleSleeper](https://github.com/NeilYager/LittleSleeper). Many kudos to Neil for writing this.

The main difference between LittleSleeper2 and Neil's is that instead of reading the audio directly from the mic, it processes the audio data from an MP3 stream hosted by a RPi.

This allows the processing and web hosting to be handled completely by the RPi or offloaded to another computer that has a python environment. I've implemented the latter.

The architecure is shown below:
