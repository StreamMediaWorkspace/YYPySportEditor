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
from windows.yytimeline_widget import YYTimelineWidget
from windows.yyplayer_widget import YYPlayerWidget, YYCutPlayerDlg


class YYMainWindow(QMainWindow, updates.UpdateWatcher):

    #for timeline
    WaveformReady = pyqtSignal(str, list)
    MaxSizeChanged = pyqtSignal(object)#not used
    refreshFrameSignal = pyqtSignal()

    def __init__(self):
        self.initialized = False

        QMainWindow.__init__(self)

        get_app().window = self
        _ = get_app()._tr

        # Load user settings for window
        s = settings.get_settings()

        self.setWindowTitle("YYSportsCoder")

        self.layout = QHBoxLayout()
        self.setLayout(self.layout)
        self.layout.addStretch(1000)

        # Add window as watcher to receive undo/redo status updates
        get_app().updates.add_watcher(self)

        # Create the timeline sync object (used for previewing timeline)
        self.timeline_sync = TimelineSync(self)

        # Setup timeline
        self.timelineWidget = YYTimelineWidget(self)
        self.layout.addWidget(self.timelineWidget)
        self.timelineWidget.PlayCutsSignal.connect(self.PlayCuts)

        self.cutPlayer = None

        # Process events before continuing
        # TODO: Figure out why this is needed for a backup recovery to correctly show up on the timeline
        #get_app().processEvents()

        self.player = YYPlayerWidget(self.timeline_sync.timeline)
        self.player.movePlayheadSignal.connect(self.timelineWidget.movePlayhead)

        self.timelineWidget.previewFrameSignal.connect(self.player.previewFrameSignal)
        self.timelineWidget.PlayCutsSignal.connect(self.PlayCuts)


        #add menu
        importAction = QAction('&Import', self)
        importAction.setShortcut('Ctrl+I')
        importAction.setStatusTip('Exit application')
        importAction.triggered.connect(self.actionImportFiles_trigger)

        menubar = self.menuBar()
        fileMenu = menubar.addMenu('&File')
        fileMenu.addAction(importAction)

        self.load_settings()

        # QTimer for Autosave
        self.auto_save_timer = QTimer(self)
        self.auto_save_timer.setInterval(s.get("autosave-interval") * 1000 * 60)
        self.auto_save_timer.timeout.connect(self.auto_save_project)
        if s.get("enable-auto-save"):
            self.auto_save_timer.start()

        # Set hardware decode
        if s.get("hardware_decode"):
            openshot.Settings.Instance().HARDWARE_DECODE = True
        else:
            openshot.Settings.Instance().HARDWARE_DECODE = False

        # Set hardware encode
        if s.get("hardware_encode"):
            openshot.Settings.Instance().HARDWARE_ENCODE = True
        else:
            openshot.Settings.Instance().HARDWARE_ENCODE = False

        # Set OMP thread enabled flag (for stability)
        if s.get("omp_threads_enabled"):
            openshot.Settings.Instance().WAIT_FOR_VIDEO_PROCESSING_TASK = False
        else:
            openshot.Settings.Instance().WAIT_FOR_VIDEO_PROCESSING_TASK = True

        # Set scaling mode to lower quality scaling (for faster previews)
        openshot.Settings.Instance().HIGH_QUALITY_SCALING = False

        # Create lock file
        self.create_lock_file()

        # Main window is initialized
        self.initialized = True
        self.player.initialized = True

        self.player.resize(800, 200);
        self.resize(800, 400)
        self.timelineWidget.resize(800, 400)
        self.show()
        self.player.show()

    # Save window settings on close
    def closeEvent(self, event):
        log.info("mainw indow close")
        # Close any tutorial dialogs
        # self.tutorial_manager.exit_manager()

        # Prompt user to save (if needed)
        '''
        if get_app().project.needs_save():
            log.info('Prompt user to save project')
            # Translate object
            _ = get_app()._tr

            # Handle exception
            ret = QMessageBox.question(self, _("Unsaved Changes"), _("Save changes to project before closing?"),
                                           QMessageBox.Cancel | QMessageBox.No | QMessageBox.Yes)
            if ret == QMessageBox.Yes:
                # Save project
                self.actionSave_trigger(event)
                event.accept()
            elif ret == QMessageBox.Cancel:
                # User canceled prompt - don't quit
                event.ignore()
                return
        '''
        # Save settings
        self.save_settings()

        # Track end of session
        # track_metric_session(False)

        # Stop threads
        #self.StopSignal.emit()

        # Process any queued events
        QCoreApplication.processEvents()

        if self.cutPlayer:
            self.cutPlayer.close()

        self.timelineWidget.close()
        # Stop preview thread (and wait for it to end)
        self.player.close()

        # Close & Stop libopenshot logger
        openshot.ZmqLogger.Instance().Close()
        get_app().logger_libopenshot.kill()

        # Destroy lock file
        self.destroy_lock_file()

        super().closeEvent(event)

    #acions
    def actionImportFiles_trigger(self, event):
        app = get_app()
        _ = app._tr
        recommended_path = app.project.get(["import_path"])
        if not recommended_path or not os.path.exists(recommended_path):
            recommended_path = os.path.join(info.HOME_PATH)
        files = QFileDialog.getOpenFileNames(self, _("Import File..."), recommended_path)[0]
        for file_path in files:
            self.add_file(file_path)
            app.updates.update(["import_path"], os.path.dirname(file_path))
            log.info("Imported media file {}".format(file_path))

    def keyPressEvent(self, event):
        current_frame = self.player.preview_thread.current_frame
        key_value = event.key()
        print(key_value)

        modifiers = int(event.modifiers())
        if (key_value > 0 and key_value != Qt.Key_Shift and key_value != Qt.Key_Alt and
                key_value != Qt.Key_Control and key_value != Qt.Key_Meta):
            # A valid keysequence was detected
            key = QKeySequence(modifiers + key_value)
        else:
            # No valid keysequence detected
            return

        # Debug
        log.info("keyPressEvent: %s" % (key.toString()))

        color = self.getColorByName("actionCut+"+key.toString())
        print("actionCut+"+key.toString(), color)
        if color:
            self.timelineWidget.cut(key.toString(), current_frame, color)
        elif key.matches(self.getShortcutByName("actionAddTrack")) == QKeySequence.ExactMatch:
            self.timelineWidget.addTrack("track_test")

    def getShortcutByName(self, setting_name):
        """ Get a key sequence back from the setting name """
        s = settings.get_settings()
        shortcut = QKeySequence(s.get(setting_name))
        return shortcut

    def getColorByName(self, setting_name):
        """ Get a key sequence back from the setting name """
        s = settings.get_settings()
        return s.get(setting_name)

    def load_settings(self):
        s = settings.get_settings()

        # Window state and geometry (also toolbar and dock locations)
        if s.get('window_state_v2'): self.restoreState(qt_types.str_to_bytes(s.get('window_state_v2')))
        if s.get('window_geometry_v2'): self.restoreGeometry(qt_types.str_to_bytes(s.get('window_geometry_v2')))

        # Load Recent Projects
        #self.load_recent_menu()

    def PlayCuts(self, cuts_json, num, den):
        #cuts_json = "[{\"id\": \"FOUFKXVQ80\",\"layer\": \"0\",\"color\": \"#fff000\",\"start\": 75.0,\"duration\": 600,\"shortCut\": \"Meta+Shift+C\",\"end\": 600.75}]"
        self.player.PauseSignal.emit()
        log.info("PlayCuts %s", cuts_json)

        import gc
        self.cutPlayer = YYCutPlayerDlg(self.timeline_sync.timeline, cuts_json, num, den)  # YYCutPlayerDlg(cuts_json, clips_json)
        self.cutPlayer.resize(200, 200)
        #self.cutPlayer.show()
        self.cutPlayer.exec_()
        del self.cutPlayer
        self.cutPlayer = None
        gc.collect()


    def create_lock_file(self):
        """Create a lock file"""
        lock_path = os.path.join(info.USER_PATH, ".lock")
        lock_value = str(uuid4())

        # Check if it already exists
        if os.path.exists(lock_path):
            # Walk the libopenshot log (if found), and try and find last line before this launch
            log_path = os.path.join(info.USER_PATH, "YYSportsCoder.log")
            last_log_line = ""
            last_stack_trace = ""
            found_stack = False
            log_start_counter = 0
            if os.path.exists(log_path):
                with open(log_path, "rb") as f:
                    # Read from bottom up
                    for raw_line in reversed(self.tail_file(f, 500)):
                        line = str(raw_line, 'utf-8')
                        # Detect stack trace
                        if "End of Stack Trace" in line:
                            found_stack = True
                            continue
                        elif "Unhandled Exception: Stack Trace" in line:
                            found_stack = False
                            continue
                        elif "libopenshot logging:" in line:
                            log_start_counter += 1
                            if log_start_counter > 1:
                                # Found the previous log start, too old now
                                break

                        if found_stack:
                            # Append line to beginning of stacktrace
                            last_stack_trace = line + last_stack_trace

                        # Ignore certain unuseful lines
                        if line.strip() and "---" not in line and "libopenshot logging:" not in line and not last_log_line:
                            last_log_line = line

            # Split last stack trace (if any)
            if last_stack_trace:
                # Get top line of stack trace (for metrics)
                last_log_line = last_stack_trace.split("\n")[0].strip()

                # Send stacktrace for debugging (if send metrics is enabled)
                track_exception_stacktrace(last_stack_trace, "YYSportsCoder")

            # Clear / normalize log line (so we can roll them up in the analytics)
            if last_log_line:
                # Format last log line based on OS (since each OS can be formatted differently)
                if platform.system() == "Darwin":
                    last_log_line = "mac-%s" % last_log_line[58:].strip()
                elif platform.system() == "Windows":
                    last_log_line = "windows-%s" % last_log_line
                elif platform.system() == "Linux":
                    last_log_line = "linux-%s" % last_log_line.replace("/usr/local/lib/", "")

                # Remove '()' from line, and split. Trying to grab the beginning of the log line.
                last_log_line = last_log_line.replace("()", "")
                log_parts = last_log_line.split("(")
                if len(log_parts) == 2:
                    last_log_line = "-%s" % log_parts[0].replace("logger_libopenshot:INFO ", "").strip()[:64]
                elif len(log_parts) >= 3:
                    last_log_line = "-%s (%s" % (log_parts[0].replace("logger_libopenshot:INFO ", "").strip()[:64], log_parts[1])
            else:
                last_log_line = ""

            # Throw exception (with last libopenshot line... if found)
            log.error("Unhandled crash detected... will attempt to recover backup project: %s" % info.BACKUP_PATH)
            #track_metric_error("unhandled-crash%s" % last_log_line, True)

            # Remove file
            self.destroy_lock_file()

        #else:
            # Normal startup, clear thumbnails
            #self.clear_all_thumbnails()

        # Write lock file (try a few times if failure)
        attempts = 5
        while attempts > 0:
            try:
                # Create lock file
                with open(lock_path, 'w') as f:
                    f.write(lock_value)
                break
            except Exception:
                attempts -= 1
                sleep(0.25)

    def destroy_lock_file(self):
        """Destroy the lock file"""
        lock_path = os.path.join(info.USER_PATH, ".lock")

        # Remove file (try a few times if failure)
        attempts = 5
        while attempts > 0:
            try:
                os.remove(lock_path)
                break
            except Exception:
                attempts -= 1
                sleep(0.25)


    def auto_save_project(self):
        """Auto save the project"""
        log.info("auto_save_project")

        # Get current filepath (if any)
        file_path = get_app().project.current_filepath
        if get_app().project.needs_save():
            if file_path:
                # A Real project file exists
                # Append .osp if needed
                if ".osp" not in file_path:
                    file_path = "%s.osp" % file_path

                # Save project
                log.info("Auto save project file: %s" % file_path)
                self.save_project(file_path)

            else:
                # No saved project found
                recovery_path = os.path.join(info.BACKUP_PATH, "backup.osp")
                log.info("Creating backup of project file: %s" % recovery_path)
                get_app().project.save(recovery_path, move_temp_files=False, make_paths_relative=False)

                # Clear the file_path (which is set by saving the project)
                get_app().project.current_filepath = None
                get_app().project.has_unsaved_changes = True

    def tail_file(self, f, n, offset=None):
        """Read the end of a file (n number of lines)"""
        avg_line_length = 90
        to_read = n + (offset or 0)

        while True:
            try:
                # Seek to byte position
                f.seek(-(avg_line_length * to_read), 2)
            except IOError:
                # Byte position not found
                f.seek(0)
            pos = f.tell()
            lines = f.read().splitlines()
            if len(lines) >= to_read or pos == 0:
                # Return the lines
                return lines[-to_read:offset and -offset or None]
            avg_line_length *= 2

    # Update window settings in setting store ----todo=========
    def save_settings(self):
        log.info("save settings");
        s = settings.get_settings()

        # Save window state and geometry (saves toolbar and dock locations)
        # s.set('window_state_v2', qt_types.bytes_to_str(self.saveState()))
        # s.set('window_geometry_v2', qt_types.bytes_to_str(self.saveGeometry()))
    # Update undo and redo buttons enabled/disabled to available changes#=========todo
    def updateStatusChanged(self, undo_status, redo_status):
        log.info('updateStatusChanged')
        #self.actionUndo.setEnabled(undo_status)
        #self.actionRedo.setEnabled(redo_status)
        self.SetWindowTitle()

    def SetWindowTitle(self, profile=None):
        """ Set the window title based on a variety of factors """

        # Get translation function
        _ = get_app()._tr

        if not profile:
            profile = get_app().project.get(["profile"])

        # Determine if the project needs saving (has any unsaved changes)
        save_indicator = ""
        '''
        if get_app().project.needs_save():
            save_indicator = "*"
            self.actionSave.setEnabled(True)
        else:
            self.actionSave.setEnabled(False)
        '''

        # Is this a saved project?
        if not get_app().project.current_filepath:
            # Not saved yet
            self.setWindowTitle("%s %s [%s] - %s" % (save_indicator, _("Untitled Project"), profile, "YYSPortEditor"))
        else:
            # Yes, project is saved
            # Get just the filename
            parent_path, filename = os.path.split(get_app().project.current_filepath)
            filename, ext = os.path.splitext(filename)
            filename = filename.replace("_", " ").replace("-", " ").capitalize()
            self.setWindowTitle("%s %s [%s] - %s" % (save_indicator, filename, profile, "YYSPortEditor"))


    def add_file(self, filepath):
        path, filename = os.path.split(filepath)

        # Add file into project
        app = get_app()
        _ = get_app()._tr

        # Check for this path in our existing project data
        file = File.get(path=filepath)

        # If this file is already found, exit
        if file:
            return

        # Load filepath in libopenshot clip object (which will try multiple readers to open it)
        clip = openshot.Clip(filepath)

        # Get the JSON for the clip's internal reader
        reader = clip.Reader()
        file_data = json.loads(reader.Json())

        print("file_data:", file_data)

        # Determine media type
        if file_data["has_video"]:
            file_data["media_type"] = "video"
        elif file_data["has_audio"] and not file_data["has_video"]:
            file_data["media_type"] = "audio"

        # Save new file to the project data
        file = File()
        file.data = file_data

        # Save file
        file.save()

        self.timelineWidget.addClip(file)

        return True
