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

        # Set max size of video preview (for speed) #todo ============
        #viewport_rect = self.videoPreview.centeredViewport(self.videoPreview.width(), self.videoPreview.height())
        #timeline.SetMaxSize(viewport_rect.width(), viewport_rect.height())

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


class YYPlayerWidget(YYPlayerBaseWidget):

    def __init__(self, timeline, parent=None):
        self.timeline = timeline
        YYPlayerBaseWidget.__init__(self, timeline, parent)

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


class YYCutPlayerWidget(YYPlayerBaseWidget):

    def __init__(self, native_timeline, cuts_json, parent=None):
        try:
            import json
        except ImportError:
            import simplejson as json

        self.clips = []
        self.cuts = self.jsonToCuts(cuts_json)
        self.initTimeline(native_timeline, self.cuts)
        YYPlayerBaseWidget.__init__(self, self.timeline, parent)
        self.index = -1
        self.currentCut = None
        self.initialized = True
        self.btnPlay_clicked("play")

    def initTimeline(self, native_timeline, cuts):
        # Get some settings from the project
        fps = native_timeline.info.fps
        width = native_timeline.info.width
        height = native_timeline.info.height
        sample_rate = native_timeline.info.sample_rate
        channels = native_timeline.info.channels
        channel_layout = native_timeline.info.channel_layout

        print("=======------", channel_layout)

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

        json_timeline = json.dumps(get_app().project._data)
        self.timeline.SetJson(json_timeline)

        # Open the timeline reader
        self.timeline.Open()

        #return timeline

        '''
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
                    self.clips.append(c)
                    #c.Position = 0#cut["start"]

                    # Append missing attributes to Clip JSON
                    new_clip = json.loads(c.Json(), strict=False)
                    new_clip.SetJson(c.Json())
                    new_clip["start"] = cut["start"]
                    new_clip["end"] = cut["end"]
                    new_clip["position"] = 0#cut["start"]
                    try:
                        # Add clip for current preview file
                        c.SetJson(new_clip)
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
        '''

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
    '''
    def Slice_Triggered(self, action, clip_ids, trans_ids, playhead_position=0):
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
                right_clip.save()

                # Update thumbnail for right clip (after the clip has been created)
                self.UpdateClipThumbnail(right_clip.data)

                # Save changes again (with new thumbnail)
                self.update_clip_data(right_clip.data, only_basic_props=False, ignore_reader=True)

                if has_audio_data:
                    # Add right clip audio to cache
                    self.waveform_cache[right_clip.id] = self.waveform_cache.get(clip_id, '[]')

                    # Pass audio to javascript timeline (and render)
                    cmd = JS_SCOPE_SELECTOR + ".setAudioData('" + right_clip.id + "', " + self.waveform_cache.get(
                        right_clip.id) + ");"
                    self.page().mainFrame().evaluateJavaScript(cmd)

            # Save changes
            self.update_clip_data(clip.data, only_basic_props=False, ignore_reader=True)

        # Start timer to redraw audio waveforms
        self.redraw_audio_timer.start()

        # Loop through each transition (using the list of ids)
        for trans_id in trans_ids:
            # Get existing transition object
            trans = Transition.get(id=trans_id)
            if not trans:
                # Invalid transition, skip to next item
                continue

            if action == MENU_SLICE_KEEP_LEFT or action == MENU_SLICE_KEEP_BOTH:
                # Get details of original transition
                position_of_tran = float(trans.data["position"])

                # Set new 'end' of transition
                trans.data["end"] = playhead_position - position_of_tran

            elif action == MENU_SLICE_KEEP_RIGHT:
                # Get details of transition clip
                position_of_tran = float(trans.data["position"])
                end_of_tran = float(trans.data["end"])

                # Set new 'end' of transition
                trans.data["position"] = playhead_position
                trans.data["end"] = end_of_tran - (playhead_position - position_of_tran)

            if action == MENU_SLICE_KEEP_BOTH:
                # Add the 2nd transition (the right side, since the left side has already been adjusted above)
                # Get right side transition object
                right_tran = Transition.get(id=trans_id)
                if not right_tran:
                    # Invalid transition, skip to next item
                    continue

                # Remove the ID property from the transition (so it becomes a new one)
                right_tran.id = None
                right_tran.type = 'insert'
                right_tran.data.pop('id')
                right_tran.key.pop(1)

                # Get details of original transition
                position_of_tran = float(right_tran.data["position"])
                end_of_tran = float(right_tran.data["end"])

                # Set new 'end' of right_tran
                right_tran.data["position"] = playhead_position + frame_duration
                right_tran.data["end"] = end_of_tran - (playhead_position - position_of_tran) + frame_duration

                # Save changes
                right_tran.save()

                # Save changes again (right side)
                self.update_transition_data(right_tran.data, only_basic_props=False)

            # Save changes (left side)
            self.update_transition_data(trans.data, only_basic_props=False)

    '''