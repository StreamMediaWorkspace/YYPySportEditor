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
from PyQt5.Qt import QWidget
from PyQt5.QtWidgets import *
import openshot  # Python module for libopenshot (required video editing module installed separately)

from classes import info, ui_util, settings, qt_types, updates

from windows.video_widget import VideoWidget
from windows.preview_thread import PreviewParent

class Player(QWidget, updates.UpdateWatcher):
    file_lists = []
    current_timeline = None
    initialized = False

    previewFrameSignal = pyqtSignal(int)
    refreshFrameSignal = pyqtSignal()

    LoadFileSignal = pyqtSignal(str)
    PlaySignal = pyqtSignal(int)
    PauseSignal = pyqtSignal()
    StopSignal = pyqtSignal()
    SeekSignal = pyqtSignal(int)
    SpeedSignal = pyqtSignal(float)

    def __init__(self):
        QWidget.__init__(self)
        # Setup video preview QWidget
        self.videoPreview = VideoWidget()
        #self.layout().insertWidget(0, self.videoPreview)
        wlayout = QHBoxLayout()
        wlayout.addWidget(self.videoPreview)
        self.setLayout(wlayout)

        # Start the preview thread
        self.preview_parent = PreviewParent(self)
        self.preview_parent.MInit(self, self.videoPreview)
        self.preview_thread = self.preview_parent.worker
        self.setFixedSize(600, 800);
        self.initialized = True

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

    def open(self, filename):
        self.LoadFileSignal.emit(filename)

    def play(self):
        self.PlaySignal.emit(99999)

    def pause(self):
        self.PauseSignal.emit()

    def stop(self):
        self.StopSignal.emit()

    def seek(self, position):
        self.SeekSignal.emit(position)

    def speed(self, sd):
        self.SpeedSignal.emit(sd)