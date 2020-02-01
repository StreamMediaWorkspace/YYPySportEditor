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

MENU_SLICE_KEEP_BOTH = 0
MENU_SLICE_KEEP_LEFT = 1
MENU_SLICE_KEEP_RIGHT = 2


class YYPlayerHover(QWidget, updates.UpdateWatcher):

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
            self.btnPlay.setText("play")
            #self.actionPlay.trigger()

    def onRewind(self):
        # Get the video player object
        player = self.player.preview_thread.player

        if player.Speed() - 1 != 0:
            self.player.SpeedSignal.emit(player.Speed() - 1)
        else:
            self.player.SpeedSignal.emit(player.Speed() - 2)

        if self.player.Mode() == openshot.PLAYBACK_PAUSED or self.player.Mode() == openshot.PLAYBACK_STOPPED:
            self.btnPlay.setText("pause")
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

class YYPlayerBase():
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

    def __init__(self, timeline):
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        # Setup video preview QWidget
        self.videoPreview = VideoWidget(self)
        self.layout.addWidget(self.videoPreview)

        # Set max size of video preview (for speed) #todo ============
        #viewport_rect = self.videoPreview.centeredViewport(self.videoPreview.width(), self.videoPreview.height())
        #timeline.SetMaxSize(viewport_rect.width(), viewport_rect.height())

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

        del self.preview_thread.player
        self.preview_thread.player = None

        del self.preview_thread
        self.preview_thread = None

        del self.preview_parent.background
        self.preview_parent.background = None

        del self.preview_parent
        self.preview_parent = None


    def btnPlay_clicked(self, force=None):
        # Determine max frame (based on clips)
        timeline_length = 0.0
        fps = self.timeline.info.fps.ToFloat()
        clips = self.timeline.Clips()
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
            # ui_util.setup_icon(self, self.actionPlay, "actionPlay", "media-playback-pause")
            self.PlaySignal.emit(timeline_length_int)

        else:
            # ui_util.setup_icon(self, self.actionPlay, "actionPlay")  # to default
            self.PauseSignal.emit()

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


class YYPlayerWidget(YYPlayerBase, QWidget):

    def __init__(self, timeline, parent=None):
        self.timeline = timeline
        QWidget.__init__(self, parent)
        YYPlayerBase.__init__(self, timeline)

    def movePlayhead(self, position_frames):
        """Update playhead position"""
        # Notify preview thread
        #self.timeline.movePlayhead(position_frames)
        self.movePlayheadSignal.emit(position_frames)

    def onPlayFinished(self):
        self.btnPlay_clicked("pause")

    #todo not used
    def handlePausedVideo(self):
        print("handlePausedVideo")
        """Handle the pause signal, by refreshing the properties dialog"""
        #self.propertyTableView.select_frame(self.preview_thread.player.Position())


class YYCutPlayerDlg(YYPlayerBase, QDialog):

    def __init__(self, native_timeline, cuts_json, num, den, parent=None):
        try:
            import json
        except ImportError:
            import simplejson as json

        self.clips = []
        self.cuts = self.jsonToCuts(cuts_json)
        self.initTimeline(native_timeline, self.cuts, num, den)
        QDialog.__init__(self, parent)
        YYPlayerBase.__init__(self, self.timeline)
        self.index = -1
        self.currentCut = None
        self.initialized = True
        self.btnPlay_clicked("play")

    def initTimeline(self, native_timeline, cuts, num, den):
        # Get some settings from the project
        fps = native_timeline.info.fps
        width = native_timeline.info.width
        height = native_timeline.info.height
        sample_rate = native_timeline.info.sample_rate
        channels = native_timeline.info.channels
        channel_layout = native_timeline.info.channel_layout

        # Create new "export" openshot.Timeline object
        self.timeline = openshot.Timeline(width, height, openshot.Fraction(fps.num, fps.den),
                                          sample_rate, channels, channel_layout)

        self.timeline.info.channel_layout = native_timeline.info.channel_layout
        self.timeline.info.has_audio = native_timeline.info.has_audio
        self.timeline.info.has_video = native_timeline.info.has_video
        self.timeline.info.video_length = native_timeline.info.video_length
        self.timeline.info.duration = native_timeline.info.duration
        self.timeline.info.sample_rate = native_timeline.info.sample_rate
        self.timeline.info.channels = native_timeline.info.channels

        #json_timeline = json.dumps(get_app().project._data)
        #self.timeline.SetJson(json_timeline)

        # Open the timeline reader
        #self.timeline.Open()

        #return timeline
        fps = float(num)/float(den)
        clips = self.getNativeClips()
        for cut in cuts:
            start = (int(cut["start"])-1) / fps
            end = (int(cut["end"])) / fps

            print("cut start-end", cut["start"], "-", cut["end"], "[", start, "-", end, "]")
            intersecting_clips = self.getIntersectClips(clips, start)
            if intersecting_clips:
                for clip in intersecting_clips:
                    path = clip["reader"]["path"]
                    c = openshot.Clip(path)
                    self.clips.append(c)
                    #c.Position(clip["position"])
                    c.Layer(0)
                    c.Position(0)
                    c.Start(start)
                    c.End(end)
                    self.video_length = end-start
                    print("=======self.video_length:", self.video_length)
                    #self.timeline.info.video_length = str(self.video_length)
                    self.timeline.info.duration = end-start

                    #data = {"start": start, "end": end}

                    #c.SetJsonValue(json.dumps(data))

                    try:
                        c.display = openshot.FRAME_DISPLAY_CLIP
                        self.timeline.AddClip(c)

                        print("---------", c.Json())
                    except:
                        log.error('Failed to add into preview video player: %s' % c.Json())

                # Get list of clip ids
                #clip_ids = [c.id for c in intersecting_clips]
                #self.timeline.Slice_Triggered(0, clip_ids, trans_ids, playhead_position)
        # Open and set reader
        self.timeline.Open()

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

    def btnPlay_clicked(self, force=None):
        if force == "pause":
            self.hover.btnPlay.setChecked(False)
        elif force == "play":
            self.hover.btnPlay.setChecked(True)

        if self.hover.btnPlay.isChecked():
            # ui_util.setup_icon(self, self.actionPlay, "actionPlay", "media-playback-pause")
            print("======video_length", self.video_length)
            self.PlaySignal.emit(self.video_length)

        else:
            # ui_util.setup_icon(self, self.actionPlay, "actionPlay")  # to default
            self.PauseSignal.emit()


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

    def jsonToClip(self, json):
        clip = None
        try:
            if not isinstance(json, dict):
                clip = json.loads(json)
            else:
                clip = json
        except:
            # Failed to parse json, do nothing
            log.error("load clips failed %s", json)

        return clip

    def getNativeClips(self):
        json_timeline = json.dumps(get_app().project._data)
        project = None
        try:
            if not isinstance(json_timeline, dict):
                project = json.loads(json_timeline)
            else:
                project = json_timeline
        except:
            # Failed to parse json, do nothing
            log.error("load cuts failed %s", json_timeline)

        return project["clips"]

    def getIntersectClips(self, clips, value):
        ret = []
        for clip in clips:
            print("======value,position, start, end", value,clip["position"], clip["start"], clip["end"])
            if clip["position"] <= value and (clip["position"] + clip["end"] - clip["start"] >= value):
                ret.append(clip)
        print("----0000000", ret)
        return ret

    def Slice_Triggered(self, action, trans_ids, playhead_position=0):
        """Callback for slice context menus"""
        # Get FPS from project
        fps = get_app().project.get(["fps"])
        fps_num = float(fps["num"])
        fps_den = float(fps["den"])
        fps_float = fps_num / fps_den
        frame_duration = fps_den / fps_num

        # Get the nearest starting frame position to the playhead (this helps to prevent cutting
        # in-between frames, and thus less likely to repeat or skip a frame).
        playhead_position = float(round((playhead_position * fps_num) / fps_den) * fps_den) / fps_num

        clip_ids = self.timeline.Clips()
        # Loop through each clip (using the list of ids)
        for clip_id in clip_ids:

            # Get existing clip object
            clip = Clip.get(id=clip_id)
            if not clip:
                # Invalid clip, skip to next item
                continue

            # Determine if waveform needs to be redrawn
            has_audio_data = clip_id in self.waveform_cache

            if action == MENU_SLICE_KEEP_LEFT or action == MENU_SLICE_KEEP_BOTH:
                # Get details of original clip
                position_of_clip = float(clip.data["position"])
                start_of_clip = float(clip.data["start"])

                # Set new 'end' of clip
                clip.data["end"] = start_of_clip + (playhead_position - position_of_clip)

            elif action == MENU_SLICE_KEEP_RIGHT:
                # Get details of original clip
                position_of_clip = float(clip.data["position"])
                start_of_clip = float(clip.data["start"])

                # Set new 'end' of clip
                clip.data["position"] = playhead_position
                clip.data["start"] = start_of_clip + (playhead_position - position_of_clip)

                # Update thumbnail for right clip (after the clip has been created)
                self.UpdateClipThumbnail(clip.data)

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
                #right_clip.save()

                # Update thumbnail for right clip (after the clip has been created)
                #self.UpdateClipThumbnail(right_clip.data)

                # Save changes again (with new thumbnail)
                #self.update_clip_data(right_clip.data, only_basic_props=False, ignore_reader=True)

                '''
                if has_audio_data:
                    # Add right clip audio to cache
                    self.waveform_cache[right_clip.id] = self.waveform_cache.get(clip_id, '[]')

                    # Pass audio to javascript timeline (and render)
                    cmd = JS_SCOPE_SELECTOR + ".setAudioData('" + right_clip.id + "', " + self.waveform_cache.get(
                        right_clip.id) + ");"
                    self.page().mainFrame().evaluateJavaScript(cmd)
                '''

            # Save changes
            #self.update_clip_data(clip.data, only_basic_props=False, ignore_reader=True)

        # Start timer to redraw audio waveforms
        #self.redraw_audio_timer.start()

