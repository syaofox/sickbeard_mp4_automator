import os
import time
import json
import sys
import shutil
from converter import Converter
from extensions import valid_input_extensions, valid_output_extensions, bad_subtitle_codecs, valid_subtitle_extensions
from qtfaststart import processor, exceptions


class MkvtoMp4:
    def __init__(self, settings=None, FFMPEG_PATH="FFMPEG.exe", FFPROBE_PATH="FFPROBE.exe", delete=True, output_extension='mp4', output_dir=None, relocate_moov=True, video_codec='h264', audio_codec='aac', audio_bitrate=None, iOS=False, awl=None, swl=None, adl=None, sdl=None, processMP4=False):
        # Settings
        self.FFMPEG_PATH=FFMPEG_PATH
        self.FFPROBE_PATH=FFPROBE_PATH
        self.delete=delete
        self.output_extension=output_extension
        self.output_dir=output_dir
        self.relocate_moov=relocate_moov
        self.processMP4=processMP4
        #Video settings
        self.video_codec=video_codec
        #Audio settings
        self.audio_codec=audio_codec
        self.audio_bitrate=audio_bitrate
        self.iOS=iOS
        self.awl=awl
        self.adl=adl
        #Subtitle settings
        self.swl=swl
        self.sdl=sdl

        #Import settings
        if settings is not None: self.importSettings(settings)
        self.options = None

    def importSettings(self, settings):
        self.FFMPEG_PATH=settings.ffmpeg
        self.FFPROBE_PATH=settings.ffprobe
        self.delete=settings.delete
        self.output_extension=settings.output_extension
        self.output_dir=settings.output_dir
        self.relocate_moov=settings.relocate_moov
        self.processMP4=settings.processMP4
        #Video settings
        #self.video_codec=settings.vcodec
        #Audio settings
        self.audio_codec=settings.acodec
        #self.audio_bitrate=settings.abitrate
        self.iOS=settings.iOS
        self.awl=settings.awl
        self.adl=settings.adl
        #Subtitle settings
        self.swl=settings.swl
        self.sdl=settings.sdl

    def process(self, inputfile, reportProgress=False):
        delete = self.delete
        deleted = False
        options = None
        if not self.validSource: return False

        if self.needProcessing(inputfile):
            options = self.generateOptions(inputfile)
            if reportProgress: print json.dumps(options, sort_keys=False, indent=4)
            outputfile = self.convert(inputfile, options, reportProgress)
        else:
            outputfile = inputfile
            if self.output_dir is not None:
                try:                
                    outputfile = os.path.join(self.output_dir, os.path.split(inputfile)[1])
                    shutil.copy(inputfile, outputfile)
                except Exception as e:
                    print "Error moving file to output directory"
                    print e
                    delete = False
            else:
                delete = False

        if delete:
            if self.removeFile(self.inputfile):
                print self.inputfile + " deleted"
                deleted = True
            else:
                print "Couldn't delete the original file:" + self.inputfile

        dim = self.getDimensions(outputfile)

        return { 'input': inputfile,
                 'output': outputfile,
                 'options': options,
                 'input_deleted': deleted,
                 'x': dim['x'],
                 'y': dim['y'] }

    #Determine if a source video file is in a valid format
    def validSource(self, inputfile):
        input_dir, filename, input_extension = self.parseFile(inputfile)
        if (input_extension in valid_input_extensions or input_extension in valid_output_extensions) and os.path.isfile(inputfile):
            return True
        else:
            return False            

    #Determine if a file meets the criteria for processing
    def needProcessing(self, inputfile):
        input_dir, filename, input_extension = self.parseFile(inputfile)
        if (input_extension in valid_input_extensions or (self.processMP4 is True and input_extension in valid_output_extensions)) and self.output_extension in valid_output_extensions:
            return True
        else:
            return False

    # Get values for width and height to be passed to the tagging classes for proper HD tags
    def getDimensions(self, inputfile):
        if self.validSource(inputfile): info = Converter(self.FFMPEG_PATH, self.FFPROBE_PATH).probe(inputfile)
        
        return { 'y': info.video.video_height,
                 'x': info.video.video_width }

    def generateOptions(self, inputfile):    
        #Get path information from the input file
        input_dir, filename, input_extension = self.parseFile(inputfile)

        # Make sure input and output extensions are compatible. If processMP4 is true, then make sure the input extension is a valid output extension and allow to proceed as well
        info = Converter(self.FFMPEG_PATH, self.FFPROBE_PATH).probe(inputfile)
       
        #Video stream
        print "Video codec detected: " + info.video.codec
        vcodec = 'copy' if info.video.codec == self.video_codec else self.video_codec

        #Audio streams
        audio_settings = {}
        l = 0
        for a in info.audio:
            print "Audio stream detected: " + a.codec + " " + a.language + " [Stream " + str(a.index) + "]"
            # Set undefined language to default language if specified
            if self.adl is not None and a.language == 'und':
                print "Undefined language detected, defaulting to " + self.adl
                a.language = self.adl
            # Proceed if no whitelist is set, or if the language is in the whitelist
            if self.awl is None or a.language in self.awl:
                # Create iOS friendly audio stream if the default audio stream has too many channels (iOS only likes AAC stereo)
                if self.iOS:
                    if a.audio_channels > 2:
                        print "Creating dual audio channels for iOS compatability for this stream"
                        audio_settings.update({l: {
                            'map': a.index,
                            'codec': 'aac',
                            'channels': 2,
                            'bitrate': 512,
                            'language': a.language,
                        }})
                        l += 1
                # If the iOS audio option is enabled and the source audio channel is only stereo, the additional iOS channel will be skipped and a single AAC 2.0 channel will be made regardless of codec preference to avoid multiple stereo channels
                acodec = 'aac' if self.iOS and a.audio_channels == 2 else self.audio_codec
                # If desired codec is the same as the source codec, copy to avoid quality loss
                acodec = 'copy' if a.codec == acodec else acodec

                # Bitrate calculations/overrides
                if self.audio_bitrate is None or self.audio_bitrate > (a.audio_channels * 256):
                    abitrate = 256 * a.audio_channels
                else:
                    abitrate = self.audio_bitrate

                audio_settings.update({l: {
                    'map': a.index,
                    'codec': acodec,
                    'channels': a.audio_channels,
                    'bitrate': abitrate,
                    'language': a.language,
                }})
                l = l + 1

        # Subtitle streams
        subtitle_settings = {}
        l = 0
        for s in info.subtitle:
            print "Subtitle stream detected: " + s.codec + " " + s.language + " [Stream " + str(s.index) + "]"

            # Make sure its not an image based codec
            if s.codec not in bad_subtitle_codecs:
                # Set undefined language to default language if specified
                if self.sdl is not None and s.language == 'und':
                    s.language = self.sdl
                # Proceed if no whitelist is set, or if the language is in the whitelist
                if self.swl is None or s.language in self.swl:
                    subtitle_settings.update({l: {
                        'map': s.index,
                        'codec': 'mov_text',
                        'language': s.language,
                        'forced': s.sub_forced,
                        'default': s.sub_default
                    }})
                    l = l + 1

        # External subtitle import
        src = 1  # FFMPEG input source number
        for dirName, subdirList, fileList in os.walk(input_dir):
            # Walk through files in the same directory as input video
            for fname in fileList:
                subname, subextension = os.path.splitext(fname)
                # Watch for appropriate file extension
                if subextension[1:] in valid_subtitle_extensions:
                    x, lang = os.path.splitext(subname)
                    # If subtitle file name and input video name are the same, proceed
                    if x == filename and len(lang) is 3:
                        print "External subtitle file detected, language " + lang[1:]
                        if self.swl is None or lang[1:] in self.swl:
                            print "Importing %s subtitle stream" % (fname)
                            subtitle_settings.update({l: {
                                'path': os.path.join(input_dir, fname),
                                'source': src,
                                'map': 0,
                                'codec': 'mov_text',
                                'language': lang[1:],
                                }})
                            l = l + 1
                            src = src + 1
                        else:
                            print "Ignoring %s external subtitle stream due to language: %s" % (fname, lang)

        # Collect all options
        options = {
            'format': 'mp4',
            'video': {
                'codec': vcodec,
                'map': info.video.index,
                'bitrate': info.format.bitrate
            },
            'audio': audio_settings,
            'subtitle': subtitle_settings,
        }
        self.inputfile = inputfile
        self.options = options
        return options

    def convert(self, inputfile, options, reportProgress=False):
        input_dir, filename, input_extension = self.parseFile(inputfile)
        output_dir = input_dir if self.output_dir is None else self.output_dir
        outputfile = os.path.join(output_dir, filename + "." + self.output_extension)
        #If we're processing a file that's going to have the same input and output filename, resolve the potential future naming conflict
        if self.inputfile == outputfile:
            newfile = os.path.join(input_dir, filename + '.tmp.' + self.input_extension)
            #Make sure there isn't any leftover temp files for whatever reason
            self.removeFile(newfile, 0, 0)
            #Attempt to rename the new input file to a temporary name
            try:
                os.rename(self.inputfile, newfile)
                self.inputfile = newfile
            except: 
                i = 1
                while os.path.isfile(outputfile):
                    outputfile = os.path.join(output_dir, filename + "(" + str(i) + ")." + self.output_extension)
                    i += i

        conv = Converter(self.FFMPEG_PATH, self.FFPROBE_PATH).convert(self.inputfile, outputfile, options, timeout=None)

        for timecode in conv:
            if reportProgress:
                sys.stdout.write('[{0}] {1}%\r'.format('#' * (timecode / 10) + ' ' * (10 - (timecode / 10)), timecode))
                sys.stdout.flush()
        print outputfile + " created"
        
        os.chmod(outputfile, 0777) # Set permissions of newly created file
        return outputfile

    def parseFile(self, path):
        input_dir, filename = os.path.split(path)
        filename, input_extension = os.path.splitext(filename)
        input_extension = input_extension[1:]
        return input_dir, filename, input_extension

    def QTFS(self, inputfile):
        input_dir, filename, input_extension = self.parseFile(inputfile)
        temp_ext = '.QTFS'
        # Relocate MOOV atom to the very beginning. Can double the time it takes to convert a file but makes streaming faster
        if self.parseFile(inputfile)[2] in valid_output_extensions and os.path.isfile(inputfile):
            print "Relocating MOOV atom to start of file"
            outputfile = inputfile + temp_ext

            # Clear out the temp file if it exists
            self.removeFile(outputfile, 0, 0)

            try:
                processor.process(inputfile, outputfile)
                os.chmod(outputfile, 0777)
                # Cleanup
                if self.removeFile(inputfile, replacement=outputfile):
                    print 'Temporary file %s deleted' % (inputfile)
                    return outputfile
                else:
                    print "Error cleaning up QTFS temp files"
                    return False
            except exceptions.FastStartException:
                print "QT FastStart did not run - perhaps moov atom was at the start already"
                return inputfile

    def removeFile(self, filename, retries=2, delay=10, replacement=None):
        for i in range(retries + 1):
            try:
                # Make sure file isn't read-only
                os.chmod(filename, 0777)
                os.remove(filename)
                # Replaces the newly deleted file with another by renaming (replacing an original with a newly created file)
                if replacement is not None:
                    os.rename(replacement, filename)
                    filename = replacement
                break
            except OSError:
                if delay > 0:
                    time.sleep(delay)
        return False if os.path.isfile(filename) else True
