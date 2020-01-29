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

from windows.views.timeline_webview import TimelineWebView
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


class YYTimelineWidget(QWidget, updates.UpdateWatcher):
    LoadFileSignal = pyqtSignal(str)
    previewFrameSignal = pyqtSignal(int)

    PlayCutsSignal = pyqtSignal(str)

    def __init__(self, parent=None):
        QWidget.__init__(self, parent)
        _ = get_app()._tr  # Get translation function

        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        # Add Timeline toolbar
        self.timelineToolbar = QToolBar("Timeline Toolbar", self)

        hlayout = QHBoxLayout()
        hlayout.addWidget(QPushButton("deded"))
        self.layout.addLayout(hlayout)

        #self.timelineToolbar.addAction(self.actionAddTrack)
        self.timelineToolbar.addSeparator()

        # rest of options
        #self.timelineToolbar.addAction(self.actionSnappingTool)
        #self.timelineToolbar.addAction(self.actionRazorTool)
        self.timelineToolbar.addSeparator()
        #self.timelineToolbar.addAction(self.actionAddMarker)
        #self.timelineToolbar.addAction(self.actionPreviousMarker)
        #self.timelineToolbar.addAction(self.actionNextMarker)
        self.timelineToolbar.addSeparator()

        # Get project's initial zoom value
        initial_scale = get_app().project.get(["scale"]) or 15
        # Round non-exponential scale down to next lowest power of 2
        initial_zoom = secondsToZoom(initial_scale)

        # Setup Zoom slider
        self.sliderZoom = QSlider(Qt.Horizontal, self)
        self.sliderZoom.setPageStep(1)
        self.sliderZoom.setRange(0, 30)
        self.sliderZoom.setValue(initial_zoom)
        self.sliderZoom.setInvertedControls(True)
        self.sliderZoom.resize(100, 16)

        self.zoomScaleLabel = QLabel(_("{} seconds").format(zoomToSeconds(self.sliderZoom.value())))

        # add zoom widgets
        #self.timelineToolbar.addAction(self.actionTimelineZoomIn)
        self.timelineToolbar.addWidget(self.sliderZoom)
        #self.timelineToolbar.addAction(self.actionTimelineZoomOut)
        self.timelineToolbar.addWidget(self.zoomScaleLabel)

        # Add timeline toolbar to web frame
        self.layout.addWidget(self.timelineToolbar)

        # Setup timeline
        self.timeline = TimelineWebView(self)
        self.layout.addWidget(self.timeline)
        self.timeline.PlayCutsSignal.connect(self.PlayCutsSignal)


    def movePlayhead(self, position_frames):
        """Update playhead position"""
        # Notify preview thread
        self.timeline.movePlayhead(position_frames)

    def addClip(self, file):
        self.timeline.addNewClip(file)

    def previewFrame(self, position_frames):
        """Preview a specific frame"""
        # Notify preview thread
        self.previewFrameSignal.emit(position_frames)

    def addTrack(self, name):
        log.info("add track %s", name);
        # Get # of tracks
        all_tracks = get_app().project.get(["layers"])
        track_number = 1000000
        if len(list(reversed(sorted(all_tracks, key=itemgetter('number'))))) > 0:
            track_number = list(reversed(sorted(all_tracks, key=itemgetter('number'))))[0].get("number") + 1000000

        # Create new track above existing layer(s)
        track = Track()
        track.data = {"number": track_number, id: str(len(all_tracks)), "y": 0, "label": "", "lock": False, "name": name}
        track.save()
        return track

    '''
    def cut(self, key, current_frame, color):
        # Timeline keyboard shortcuts
        playhead_position = current_frame
        intersecting_clips = Clip.filter(intersect=playhead_position)
        #intersecting_trans = Transition.filter(intersect=playhead_position)
        if intersecting_clips# or intersecting_trans:
            # Get list of clip ids
            clip_ids = [c.id for c in intersecting_clips]
            #trans_ids = [t.id for t in intersecting_trans]
            #self.timeline.Slice_Triggered(0, clip_ids, trans_ids, playhead_position)
            self.timeline.Slice_Cut_Triggered(0, clip_ids, key, color, playhead_position)
    '''

    def cut(self, key, current_frame, color):
        log.info("add cut %s,%s, %s", key, current_frame, color)

        # Get # of tracks
        find = False
        cutList = Cut.filter(shortCut=key)
        for cut in cutList:
            if cut and cut.data["end"] == -1:
                cut.data["end"] = current_frame
                cut.save()
                find = True

        # Create new track above existing layer(s)
        if not find:
            id = len(get_app().project.get(["cuts"]))
            cut = Cut()
            cut.data = {"id": str(id), "layer": "0", "color": color, "start": current_frame, "duration": 0.0, "shortCut": key, "end": -1}
            cut.save()

    def PlayCuts(self, cuts_json):
        self.PlayCutsSignal.emit(cuts_json)