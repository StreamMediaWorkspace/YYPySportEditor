import os
import sys
import platform
import shutil
import webbrowser
from operator import itemgetter
from uuid import uuid4
from copy import deepcopy
from time import sleep

from PyQt5.QtCore import *
from PyQt5.QtGui import QIcon, QCursor, QKeySequence
from PyQt5.QtWidgets import *
import openshot  # Python module for libopenshot (required video editing module installed separately)


from classes import info, ui_util, settings, qt_types, updates
from classes.app import get_app
from classes.logger import log
from classes.timeline import TimelineSync
from classes.query import File, Clip, Transition, Marker, Track, Cut
from classes.metrics import *
from classes.version import *
from classes.conversion import zoomToSeconds, secondsToZoom
from images import openshot_rc

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

from windows.video_widget import VideoWidget
from windows.preview_thread import PreviewParent

class YYPlayerHover(QWidget,  updates.UpdateWatcher):

    def __init__(self, player, parent=None):
        QWidget.__init__(self, parent)
        self.player = player
        layout = QHBoxLayout()
        layout.setSpacing(0)
        self.setLayout(layout)

        rewindButton = QPushButton("rewind")
        layout.addWidget(rewindButton)
        rewindButton.clicked.connect(self.onRewind)

        self.btnPlay = QPushButton("play")
        self.btnPlay.setCheckable(True)
        layout.addWidget(self.btnPlay)
        self.btnPlay.clicked.connect(self.player.btnPlay_clicked)

        fastForwardButton = QPushButton("fast")
        layout.addWidget(fastForwardButton)
        fastForwardButton.clicked.connect(self.onFastForward)

        self.player.PlayModeChangedSignal.connect(self.PlayModeChanged)

        self.resize(150, 50)

    def onFastForward(self, event):
        # Get the video player object
        player = self.player.preview_thread.player

        if player.Speed() + 1 != 0:
            self.player.SpeedSignal.emit(player.Speed() + 1)
        else:
            self.player.SpeedSignal.emit(player.Speed() + 2)

        if player.Mode() == openshot.PLAYBACK_PAUSED or player.Mode() == openshot.PLAYBACK_STOPPED:
            self.playButotn.setText("play")
            #self.actionPlay.trigger()

    def onRewind(self):
        # Get the video player object
        player = self.player.preview_thread.player

        if player.Speed() - 1 != 0:
            self.player.SpeedSignal.emit(player.Speed() - 1)
        else:
            self.player.SpeedSignal.emit(player.Speed() - 2)

        if self.player.Mode() == openshot.PLAYBACK_PAUSED or self.player.Mode() == openshot.PLAYBACK_STOPPED:
            self.playButotn.setText("pause")
            #self.player.actionPlay.trigger()

    '''
    def onPlayOrStop(self):
        self.player.SpeedSignal.emit(0)
        if self.player.Mode() == openshot.PLAYBACK_PAUSED or self.player.Mode() == openshot.PLAYBACK_STOPPED:
            #self.playPauseButotn.setText("play")
            self.player.btnPlay_clicked(None, "play")
        else:
            #self.playPauseButotn.setText("pause")
            self.player.btnPlay_clicked(None, "pause")
    '''

    def PlayModeChanged(self, mode):
        print("====PlayModeChanged===", mode, openshot.PLAYBACK_PLAY, openshot.PLAYBACK_LOADING, openshot.PLAYBACK_PAUSED, openshot.PLAYBACK_STOPPED)
        if self.player.Mode() == openshot.PLAYBACK_PAUSED or self.player.Mode() == openshot.PLAYBACK_STOPPED:
            self.btnPlay.setText("play")
        else:
            self.btnPlay.setText("pause")

class YYPlayerBaseWidget(QWidget, updates.UpdateWatcher):
    previewFrameSignal = pyqtSignal(int)
    refreshFrameSignal = pyqtSignal()
    LoadFileSignal = pyqtSignal(str)
    PlaySignal = pyqtSignal(int)
    PauseSignal = pyqtSignal()
    StopSignal = pyqtSignal()
    SeekSignal = pyqtSignal(int)
    SpeedSignal = pyqtSignal(float)

    movePlayheadSignal = pyqtSignal(float)
    PlayModeChangedSignal = pyqtSignal(int)
    MaxSizeChanged = pyqtSignal(object)

    def __init__(self, timeline, parent=None):
        QWidget.__init__(self, parent)
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        # Setup video preview QWidget
        self.videoPreview = VideoWidget(self)
        self.layout.addWidget(self.videoPreview)

        # Set max size of video preview (for speed)
        viewport_rect = self.videoPreview.centeredViewport(self.videoPreview.width(), self.videoPreview.height())
        timeline.SetMaxSize(viewport_rect.width(), viewport_rect.height())

        self.setLayout(self.layout)

        self.initialized = False

        # Start the preview thread
        self.preview_parent = PreviewParent()
        self.preview_parent.Init(self, timeline, self.videoPreview)
        self.preview_thread = self.preview_parent.worker

        # Set pause callback
        self.PauseSignal.connect(self.handlePausedVideo)

        self.hover = YYPlayerHover(self, self)

    # Save window settings on close
    def closeEvent(self, event):
        # Stop threads
        self.StopSignal.emit()

        # Process any queued events
        QCoreApplication.processEvents()

        # Stop preview thread (and wait for it to end)
        self.preview_thread.player.CloseAudioDevice()
        self.preview_thread.kill()
        self.preview_parent.background.exit()
        self.preview_parent.background.wait(5000)

    def btnPlay_clicked(self, force=None):
        log.info("btnPlay_clicked")

        if force == "pause":
            self.hover.btnPlay.setChecked(False)
        elif force == "play":
            self.hover.btnPlay.setChecked(True)

        if self.hover.btnPlay.isChecked():
            log.info('play (icon to pause)')
            #ui_util.setup_icon(self, self.btnPlay, "actionPlay", "media-playback-pause")
            self.preview_thread.Play(1000)#======todo
        else:
            log.info('pause (icon to play)')
            #ui_util.setup_icon(self, self.btnPlay, "actionPlay", "media-playback-start")  # to default
            self.preview_thread.Pause()

        # Send focus back to toolbar
        #self.sliderVideo.setFocus()


    def resizeEvent(self, QResizeEvent):
        super().resizeEvent(QResizeEvent)
        self.hover.setGeometry((self.width() - self.hover.width()) / 2, 20, self.hover.width(), self.hover.height())

    def onModeChanged(self, current_mode):
        log.info('onModeChanged %s', current_mode)
        self.PlayModeChangedSignal.emit(current_mode)

    def Mode(self):
        return self.preview_thread.player.Mode()

    def handlePausedVideo(self):
        log.info("base handlePausedVideo")

    def onPlayFinished(self):
        log.info("base onPlayFinished")

    def movePlayhead(self, position_frames):
        log.info("movePlayhead %s", position_frames)
        """Update playhead position"""
        # Notify preview thread
        # self.timeline.movePlayhead(position_frames)
        #self.movePlayheadSignal.emit(position_frames)


class YYPlayerWidget(YYPlayerBaseWidget):

    def __init__(self, timeline, parent=None):
        YYPlayerBaseWidget.__init__(self, timeline, parent)
        #_ = get_app()._tr  # Get translation function

        #self.resize(800, 200)

    def movePlayhead(self, position_frames):
        """Update playhead position"""
        # Notify preview thread
        #self.timeline.movePlayhead(position_frames)
        self.movePlayheadSignal.emit(position_frames)

    def onPlayFinished(self):
        self.btnPlay_clicked(None, "pause")

    def btnPlay_clicked(self, force=None):
        # Determine max frame (based on clips)
        timeline_length = 0.0
        fps = get_app().window.timeline_sync.timeline.info.fps.ToFloat()
        clips = get_app().window.timeline_sync.timeline.Clips()
        for clip in clips:
            clip_last_frame = clip.Position() + clip.Duration()
            if clip_last_frame > timeline_length:
                # Set max length of timeline
                timeline_length = clip_last_frame

        # Convert to int and round
        timeline_length_int = round(timeline_length * fps) + 1

        if force == "pause":
            self.hover.btnPlay.setChecked(False)
        elif force == "play":
            self.hover.btnPlay.setChecked(True)

        if self.hover.btnPlay.isChecked():
            #ui_util.setup_icon(self, self.actionPlay, "actionPlay", "media-playback-pause")
            self.PlaySignal.emit(timeline_length_int)
            print("---------play")

        else:
            #ui_util.setup_icon(self, self.actionPlay, "actionPlay")  # to default
            print("---------pause")
            self.PauseSignal.emit()

    #todo not used
    def handlePausedVideo(self):
        print("handlePausedVideo")
        """Handle the pause signal, by refreshing the properties dialog"""
        #self.propertyTableView.select_frame(self.preview_thread.player.Position())


class YYCutPlayerWidget(YYPlayerBaseWidget):

    def __init__(self, cuts_json, clips_json, parent=None):
        self.cuts = self.jsonToCuts(cuts_json)
        self.timeline = self.initTimeline(self.cuts, clips_json)
        YYPlayerBaseWidget.__init__(self, self.timeline, parent)
        self.index = -1
        self.currentCut = None
        self.initialized = True
        #self.actionPlay_trigger(None, "play")

    def initTimeline(self, cuts, clips_json):
        project = get_app().project
        fps = project.get(["fps"])
        width = project.get(["width"])
        height = project.get(["height"])
        sample_rate = project.get(["sample_rate"])
        channels = project.get(["channels"])
        channel_layout = project.get(["channel_layout"])
        '''
        self.file_path = file.absolute_path()
        self.video_length = int(file.data['video_length'])
        self.fps_num = int(file.data['fps']['num'])
        self.fps_den = int(file.data['fps']['den'])
        self.fps = float(self.fps_num) / float(self.fps_den)
        self.width = int(file.data['width'])
        self.height = int(file.data['height'])
        self.sample_rate = int(file.data['sample_rate'])
        self.channels = int(file.data['channels'])
        self.channel_layout = int(file.data['channel_layout'])

        # Open video file with Reader
        log.info(self.file_path)
        '''

        # Create an instance of a libopenshot Timeline object
        timeline = openshot.Timeline(width, height, openshot.Fraction(fps["num"], fps["den"]), sample_rate,
                                   channels, channel_layout)

        try:
            # Add clip for current preview file
            clip = openshot.Clip("/Users/admin/Downloads/BLACKPINK_Kill_This_Love.mp4")

            # Show waveform for audio files
            if not clip.Reader().info.has_video and clip.Reader().info.has_audio:
                clip.Waveform(True)

            # Set has_audio property
            #timeline.info.has_audio = clip.Reader().info.has_audio

            timeline.AddClip(clip)

        except:
            log.error('Failed to load media file into preview player: %s' % self.file_path)
            return None

        timeline.Open()
        return timeline
        try:
            import json
        except ImportError:
            import simplejson as json

        s = settings.get_settings()
        project = get_app().project
        # Get some settings from the project
        fps = project.get(["fps"])
        width = project.get(["width"])
        height = project.get(["height"])
        sample_rate = project.get(["sample_rate"])
        channels = project.get(["channels"])
        channel_layout = project.get(["channel_layout"])

        # Create an instance of a libopenshot Timeline object
        timeline = openshot.Timeline(width, height, openshot.Fraction(fps["num"], fps["den"]), sample_rate,
                                          channels, channel_layout)
        timeline.info.channel_layout = channel_layout
        timeline.info.has_audio = True
        timeline.info.has_video = True
        timeline.info.video_length = 99999
        timeline.info.duration = 999.99
        timeline.info.sample_rate = sample_rate
        timeline.info.channels = channels

        # Open the timeline reader
        timeline.Open()
#self.timeline.ApplyMapperToClips

        print("0------", timeline.info)
        #return timeline

        clips = self.jsonToClips(clips_json)
        print("222222222222221111", clips)
        for cut in cuts:
            intersecting_clips = self.getIntersectClips(clips, float(cut["start"]))
            print("111111111", intersecting_clips, fps)
            if intersecting_clips:
                for clip in intersecting_clips:
                    print("222222222", clip["reader"]["path"])
                    path = clip["reader"]["path"]
                    print("-----000000", path)
                    c = openshot.Clip(path)
                    #c.Start(cut["start"])
                    #c.End(cut["end"])
                    #c.Position = 0#cut["start"]

                    # Append missing attributes to Clip JSON
                    #new_clip = json.loads(c.Json(), strict=False)
                    #new_clip.SetJson(clip.Json())
                    #new_clip["start"] = cut["start"]
                    #new_clip["end"] = cut["end"]
                    #new_clip["position"] = 0#cut["start"]
                    try:
                        # Add clip for current preview file
                        #c.SetJson(new_clip)
                        c.display = openshot.FRAME_DISPLAY_CLIP

                        timeline.AddClip(c)
                        #print('add into preview video player: %s', c.Json())
                    except:
                        log.error('Failed to add into preview video player: %s' % c.Json())

                # Get list of clip ids
                #clip_ids = [c.id for c in intersecting_clips]
                #self.timeline.Slice_Triggered(0, clip_ids, trans_ids, playhead_position)
        # Open and set reader
        #timeline.Open()
        return timeline

        # Connect to signal
        #self.window.MaxSizeChanged.connect(self.MaxSizeChangedCB)

        '''
        if action.type == "load":
                # This JSON is initially loaded to libopenshot to update the timeline
                self.timeline.SetJson(action.json(only_value=True))
                self.timeline.Open()  # Re-Open the Timeline reader

                # The timeline's profile changed, so update all clips
                self.timeline.ApplyMapperToClips()

                # Refresh current frame (since the entire timeline was updated)
                self.window.refreshFrameSignal.emit()

            else:
                # This JSON DIFF is passed to libopenshot to update the timeline
                self.timeline.ApplyJsonDiff(action.json(is_array=True))
        '''
        '''
        if action == MENU_SLICE_KEEP_BOTH:
                # Add the 2nd clip (the right side, since the left side has already been adjusted above)
                # Get right side clip object
                right_clip = Clip.get(id=clip_id)
                if not right_clip:
                    # Invalid clip, skip to next item
                    continue

                # Remove the ID property from the clip (so it becomes a new one)
                right_clip.id = None
                right_clip.type = 'insert'
                right_clip.data.pop('id')
                right_clip.key.pop(1)

                # Set new 'start' of right_clip (need to bump 1 frame duration more, so we don't repeat a frame)
                right_clip.data["position"] = (round(float(playhead_position) * fps_float) + 1) / fps_float
                right_clip.data["start"] = (round(float(clip.data["end"]) * fps_float) + 2) / fps_float

                # Save changes
                right_clip.save()

                # Save changes again (with new thumbnail)
                self.update_clip_data(right_clip.data, only_basic_props=False, ignore_reader=True)

                if has_audio_data:
                    # Add right clip audio to cache
                    self.waveform_cache[right_clip.id] = self.waveform_cache.get(clip_id, '[]')

                    # Pass audio to javascript timeline (and render)
                    cmd = JS_SCOPE_SELECTOR + ".setAudioData('" + right_clip.id + "', " + self.waveform_cache.get(right_clip.id) + ");"
                    self.page().mainFrame().evaluateJavaScript(cmd)

        '''

    def getIntersectClips(self, clips, value):
        ret = []
        for clip in clips:
            print("-----09999",value, clip["position"] , clip["end"] , clip["start"])
            if clip["position"] <= value and (clip["position"] + clip["end"] - clip["start"] >= value):
                ret.append(clip)
        print("----0000000",ret)
        return ret

    def jsonToCuts(self, cuts_json):
        cuts = []
        try:
            if not isinstance(cuts_json, dict):
                cuts = json.loads(cuts_json)
            else:
                cuts = cuts_json
        except:
            # Failed to parse json, do nothing
            log.error("load cuts failed %s", cuts_json)

        return cuts

    def jsonToClips(self, clips_json):
        clips = []
        try:
            if not isinstance(clips_json, dict):
                clips = json.loads(clips_json)
            else:
                clips = clips_json
        except:
            # Failed to parse json, do nothing
            log.error("load cuts failed %s", clips_json)

        return clips

    def getNextCut(self):
        while (True):
            self.index = self.index + 1
            if len(self.cuts) < self.index + 1:
                return None

            if self.cuts[self.index]:
                return self.cuts[self.index]

    def actionPlay_trigger(self, event, force=None):
        # Determine max frame (based on clips)
        if not self.currentCut:
            self.currentCut = self.getNextCut()
            if not self.currentCut:
                log.info("play cut finished")
                if force == "play":
                    self.index = -1
                    self.currentCut = self.getNextCut()
                else:
                    return
            else:
                self.SeekSignal.emit(float(self.currentCut["start"]))

        timeline_length = float(self.currentCut["end"])
        fps = get_app().window.timeline_sync.timeline.info.fps.ToFloat()

        # Convert to int and round
        timeline_length_int = round(timeline_length * fps) + 1

        if force == None or force == "pause":
            # ui_util.setup_icon(self, self.actionPlay, "actionPlay")  # to default
            self.currentCut = self.getNextCut()
            if not self.currentCut:
                log.info("play cut finished last finished")
                self.PauseSignal.emit()
            else:
                self.SeekSignal.emit(float(self.currentCut["start"]))
                log.info("------SeekSignal-------", float(self.currentCut["start"]))
        else:
            #ui_util.setup_icon(self, self.actionPlay, "actionPlay", "media-playback-pause")
            #if timeline_length_int >= self.preview_thread.current_frame:
            #    self.SeekSignal.emit(1)#move to begine to play
            print("----play----", timeline_length_int)
            self.PlaySignal.emit(timeline_length_int)

        #QCoreApplication.processEvents()



