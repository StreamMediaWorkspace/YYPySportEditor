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
#from windows.views.tutorial import TutorialManager
from windows.video_widget import VideoWidget
from windows.preview_thread import PreviewParent

class YYMainWindow(QMainWindow, updates.UpdateWatcher):
    """ This class contains the logic for the main window widget """

    # Path to ui file
    ui_path = os.path.join(info.PATH, 'windows', 'ui', 'yy-main-window.ui')

    previewFrameSignal = pyqtSignal(int)
    refreshFrameSignal = pyqtSignal()
    LoadFileSignal = pyqtSignal(str)
    PlaySignal = pyqtSignal(int)
    PauseSignal = pyqtSignal()
    StopSignal = pyqtSignal()
    SeekSignal = pyqtSignal(int)
    SpeedSignal = pyqtSignal(float)
    RecoverBackup = pyqtSignal()
    FoundVersionSignal = pyqtSignal(str)
    WaveformReady = pyqtSignal(str, list)
    TransformSignal = pyqtSignal(str)
    ExportStarted = pyqtSignal(str, int, int)
    ExportFrame = pyqtSignal(str, int, int, int)
    ExportEnded = pyqtSignal(str)
    MaxSizeChanged = pyqtSignal(object)
    #InsertKeyframe = pyqtSignal(object)
    OpenProjectSignal = pyqtSignal(str)
    #ThumbnailUpdated = pyqtSignal(str)

    # Save window settings on close
    def closeEvent(self, event):

        # Close any tutorial dialogs
        #self.tutorial_manager.exit_manager()

        # Prompt user to save (if needed)
        if get_app().project.needs_save():
            log.info('Prompt user to save project')
            # Translate object
            _ = get_app()._tr

            # Handle exception
            ret = QMessageBox.question(self, _("Unsaved Changes"), _("Save changes to project before closing?"), QMessageBox.Cancel | QMessageBox.No | QMessageBox.Yes)
            if ret == QMessageBox.Yes:
                # Save project
                self.actionSave_trigger(event)
                event.accept()
            elif ret == QMessageBox.Cancel:
                # User canceled prompt - don't quit
                event.ignore()
                return

        # Save settings
        self.save_settings()

        # Track end of session
        track_metric_session(False)

        # Stop threads
        self.StopSignal.emit()

        # Process any queued events
        QCoreApplication.processEvents()

        # Stop preview thread (and wait for it to end)
        self.preview_thread.player.CloseAudioDevice()
        self.preview_thread.kill()
        self.preview_parent.background.exit()
        self.preview_parent.background.wait(5000)

        # Close & Stop libopenshot logger
        openshot.ZmqLogger.Instance().Close()
        get_app().logger_libopenshot.kill()

        # Destroy lock file
        self.destroy_lock_file()


    def __init__(self, mode=None):
        # Create main window base class
        QMainWindow.__init__(self)
        self.initialized = False

        # set window on app for reference during initialization of children
        get_app().window = self
        _ = get_app()._tr

        # Track metrics
        track_metric_session()  # start session

        # Load user settings for window
        s = settings.get_settings()

        # Load UI from designer
        ui_util.load_ui(self, self.ui_path)

        # Set all keyboard shortcuts from the settings file
        #self.InitKeyboardShortcuts()

        # Init UI
        ui_util.init_ui(self)

        # Setup toolbars that aren't on main window, set initial state of items, etc
        self.setup_toolbars()

        # Add window as watcher to receive undo/redo status updates
        get_app().updates.add_watcher(self)

        # Create the timeline sync object (used for previewing timeline)
        self.timeline_sync = TimelineSync(self)

        # Setup timeline
        self.timeline = TimelineWebView(self)
        self.frameWeb.layout().addWidget(self.timeline)

        # Configure the side docks to full-height
        self.setCorner(Qt.TopLeftCorner, Qt.LeftDockWidgetArea)
        self.setCorner(Qt.BottomLeftCorner, Qt.LeftDockWidgetArea)
        self.setCorner(Qt.TopRightCorner, Qt.RightDockWidgetArea)
        self.setCorner(Qt.BottomRightCorner, Qt.RightDockWidgetArea)

        # Process events before continuing
        # TODO: Figure out why this is needed for a backup recovery to correctly show up on the timeline
        get_app().processEvents()

        # Setup video preview QWidget
        self.videoPreview = VideoWidget()
        self.tabVideo.layout().insertWidget(0, self.videoPreview)

        # Load window state and geometry
        #self.load_settings()

        # Start the preview thread
        self.preview_parent = PreviewParent()
        self.preview_parent.Init(self, self.timeline_sync.timeline, self.videoPreview)
        self.preview_thread = self.preview_parent.worker

        # Set pause callback
        self.PauseSignal.connect(self.handlePausedVideo)

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

        # Connect OpenProject Signal
        self.OpenProjectSignal.connect(self.open_project)

        # Show window
        self.show()

        # Save settings
        s.save()

        # Refresh frame
        QTimer.singleShot(100, self.refreshFrameSignal.emit)

        # Main window is initialized
        self.initialized = True

    def setup_toolbars(self):
        _ = get_app()._tr  # Get translation function

        # Start undo and redo actions disabled
        self.actionUndo.setEnabled(False)
        self.actionRedo.setEnabled(False)

        # Add Video Preview toolbar
        self.videoToolbar = QToolBar("Video Toolbar")

        # Add fixed spacer(s) (one for each "Other control" to keep playback controls centered)
        ospacer1 = QWidget(self)
        ospacer1.setMinimumSize(32, 1) # actionSaveFrame
        self.videoToolbar.addWidget(ospacer1)
        #ospacer2 = QWidget(self)
        #ospacer2.setMinimumSize(32, 1) # ???
        #self.videoToolbar.addWidget(ospacer2)

        # Add left spacer
        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.videoToolbar.addWidget(spacer)

        # Playback controls (centered)
        self.videoToolbar.addAction(self.actionJumpStart)
        self.videoToolbar.addAction(self.actionRewind)
        self.videoToolbar.addAction(self.actionPlay)
        self.videoToolbar.addAction(self.actionFastForward)
        self.videoToolbar.addAction(self.actionJumpEnd)
        self.actionPlay.setCheckable(True)

        # Add right spacer
        spacer = QWidget(self)
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.videoToolbar.addWidget(spacer)

        # Other controls (right-aligned)
        #self.videoToolbar.addAction(self.actionSaveFrame)

        self.tabVideo.layout().addWidget(self.videoToolbar)

        # Add Timeline toolbar
        self.timelineToolbar = QToolBar("Timeline Toolbar", self)

        self.timelineToolbar.addAction(self.actionAddTrack)
        self.timelineToolbar.addSeparator()

        # rest of options
        self.timelineToolbar.addAction(self.actionSnappingTool)
        self.timelineToolbar.addAction(self.actionRazorTool)
        self.timelineToolbar.addSeparator()
        self.timelineToolbar.addAction(self.actionAddMarker)
        self.timelineToolbar.addAction(self.actionPreviousMarker)
        self.timelineToolbar.addAction(self.actionNextMarker)
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

        self.zoomScaleLabel = QLabel( _("{} seconds").format(zoomToSeconds(self.sliderZoom.value())) )

        # add zoom widgets
        self.timelineToolbar.addAction(self.actionTimelineZoomIn)
        self.timelineToolbar.addWidget(self.sliderZoom)
        self.timelineToolbar.addAction(self.actionTimelineZoomOut)
        self.timelineToolbar.addWidget(self.zoomScaleLabel)

        # Add timeline toolbar to web frame
        self.frameWeb.addWidget(self.timelineToolbar)

    def actionImportFiles_trigger(self, event):
        app = get_app()
        _ = app._tr
        recommended_path = app.project.get(["import_path"])
        if not recommended_path or not os.path.exists(recommended_path):
            recommended_path = os.path.join(info.HOME_PATH)
        files = QFileDialog.getOpenFileNames(self, _("Import File..."), recommended_path)[0]
        for file_path in files:
            #self.filesTreeView.add_file(file_path)
            #self.filesTreeView.refresh_view()
            self.add_file(file_path)
            app.updates.update(["import_path"], os.path.dirname(file_path))
            log.info("Imported media file {}".format(file_path))

    # Save window settings on close
    def closeEvent(self, event):

        # Close any tutorial dialogs
        #self.tutorial_manager.exit_manager()

        # Prompt user to save (if needed)
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

        # Save settings
        self.save_settings()

        # Track end of session
        #track_metric_session(False)

        # Stop threads
        self.StopSignal.emit()

        # Process any queued events
        QCoreApplication.processEvents()

        # Stop preview thread (and wait for it to end)
        self.preview_thread.player.CloseAudioDevice()
        self.preview_thread.kill()
        self.preview_parent.background.exit()
        self.preview_parent.background.wait(5000)

        # Close & Stop libopenshot logger
        openshot.ZmqLogger.Instance().Close()
        get_app().logger_libopenshot.kill()

        # Destroy lock file
        self.destroy_lock_file()

    def handlePausedVideo(self):
        print("handlePausedVideo")
        """Handle the pause signal, by refreshing the properties dialog"""
        #self.propertyTableView.select_frame(self.preview_thread.player.Position())

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

    # Update window settings in setting store
    def save_settings(self):
        log.info("save settings");
        s = settings.get_settings()

        # Save window state and geometry (saves toolbar and dock locations)
        #s.set('window_state_v2', qt_types.bytes_to_str(self.saveState()))
        #s.set('window_geometry_v2', qt_types.bytes_to_str(self.saveGeometry()))

    def create_lock_file(self):
        """Create a lock file"""
        lock_path = os.path.join(info.USER_PATH, ".lock")
        lock_value = str(uuid4())

        # Check if it already exists
        if os.path.exists(lock_path):
            # Walk the libopenshot log (if found), and try and find last line before this launch
            log_path = os.path.join(info.USER_PATH, "libopenshot.log")
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
                track_exception_stacktrace(last_stack_trace, "libopenshot")

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

    def open_project(self, file_path, clear_thumbnails=True):
        """ Open a project from a file path, and refresh the screen """

        app = get_app()
        _ = app._tr  # Get translation function

        # Do we have unsaved changes?
        if get_app().project.needs_save():
            ret = QMessageBox.question(self, _("Unsaved Changes"), _("Save changes to project first?"), QMessageBox.Cancel | QMessageBox.No | QMessageBox.Yes)
            if ret == QMessageBox.Yes:
                # Save project
                self.actionSave.trigger()
            elif ret == QMessageBox.Cancel:
                # User canceled prompt
                return

        # Set cursor to waiting
        get_app().setOverrideCursor(QCursor(Qt.WaitCursor))

        try:
            if os.path.exists(file_path):
                # Clear any previous thumbnails
                #if clear_thumbnails:
                #    self.clear_all_thumbnails()

                # Load project file
                app.project.load(file_path)

                # Set Window title
                self.SetWindowTitle()

                # Reset undo/redo history
                app.updates.reset()
                app.updates.load_history(app.project)

                # Reset selections
                self.clearSelections()

                # Refresh file tree
                self.filesTreeView.refresh_view()

                # Load recent projects again
                self.load_recent_menu()

                log.info("Loaded project {}".format(file_path))
            else:
                # If statement is required, as if the user hits "Cancel"
                # on the "load file" dialog, it is interpreted as trying
                # to open a file with a blank name. This could use some
                # improvement.
                if file_path != "":
                    # Prepare to use status bar
                    self.statusBar = QStatusBar()
                    self.setStatusBar(self.statusBar)

                    log.info("File not found at {}".format(file_path))
                    self.statusBar.showMessage(_("Project {} is missing (it may have been moved or deleted). It has been removed from the Recent Projects menu.".format(file_path)), 5000)
                    self.remove_recent_project(file_path)
                    self.load_recent_menu()

        except Exception as ex:
            log.error("Couldn't open project {}".format(file_path))
            QMessageBox.warning(self, _("Error Opening Project"), str(ex))

        # Restore normal cursor
        get_app().restoreOverrideCursor()



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

    '''
    #from files_treeview
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
        try:
            reader = clip.Reader()
            file_data = json.loads(reader.Json())

            # Determine media type
            if file_data["has_video"]:
                file_data["media_type"] = "video"
            elif file_data["has_audio"] and not file_data["has_video"]:
                file_data["media_type"] = "audio"

            # Save new file to the project data
            file = File()
            file.data = file_data

            # Is this file an image sequence / animation?
            image_seq_details = self.get_image_sequence_details(filepath)
            if image_seq_details:
                # Update file with correct path
                folder_path = image_seq_details["folder_path"]
                file_name = image_seq_details["file_path"]
                base_name = image_seq_details["base_name"]
                fixlen = image_seq_details["fixlen"]
                digits = image_seq_details["digits"]
                extension = image_seq_details["extension"]

                if not fixlen:
                    zero_pattern = "%d"
                else:
                    zero_pattern = "%%0%sd" % digits

                # Generate the regex pattern for this image sequence
                pattern = "%s%s.%s" % (base_name, zero_pattern, extension)

                # Split folder name
                (parentPath, folderName) = os.path.split(folder_path)
                if not base_name:
                    # Give alternate name
                    file.data["name"] = "%s (%s)" % (folderName, pattern)

                # Load image sequence (to determine duration and video_length)
                image_seq = openshot.Clip(os.path.join(folder_path, pattern))

                # Update file details
                file.data["path"] = os.path.join(folder_path, pattern)
                file.data["media_type"] = "video"
                file.data["duration"] = image_seq.Reader().info.duration
                file.data["video_length"] = image_seq.Reader().info.video_length

            # Save file
            file.save()
            return True

        except:
            # Handle exception
            msg = QMessageBox()
            msg.setText(_("{} is not a valid video, audio, or image file.".format(filename)))
            msg.exec_()
            return False
    '''



    #from files_treeview
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

        # open in timeline added by yanght======
        self.timeline.addNewClip(file)

        return True

    # Update undo and redo buttons enabled/disabled to available changes
    def updateStatusChanged(self, undo_status, redo_status):
        log.info('updateStatusChanged')
        self.actionUndo.setEnabled(undo_status)
        self.actionRedo.setEnabled(redo_status)
        self.SetWindowTitle()

    def SetWindowTitle(self, profile=None):
        """ Set the window title based on a variety of factors """

        # Get translation function
        _ = get_app()._tr

        if not profile:
            profile = get_app().project.get(["profile"])

        # Determine if the project needs saving (has any unsaved changes)
        save_indicator = ""
        if get_app().project.needs_save():
            save_indicator = "*"
            self.actionSave.setEnabled(True)
        else:
            self.actionSave.setEnabled(False)

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

    # Add to the selected items
    def addSelection(self, item_id, item_type, clear_existing=False):
        log.info('main::addSelection: item_id: %s, item_type: %s, clear_existing: %s' % (item_id, item_type, clear_existing))

        '''
        # Clear existing selection (if needed)
        if clear_existing:
            if item_type == "clip":
                self.selected_clips.clear()

        if item_id:
            # If item_id is not blank, store it
            if item_type == "clip" and item_id not in self.selected_clips:
                self.selected_clips.append(item_id)
        '''

    def movePlayhead(self, position_frames):
        """Update playhead position"""
        # Notify preview thread
        self.timeline.movePlayhead(position_frames)

    def actionPlay_trigger(self, event, force=None):

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
            self.actionPlay.setChecked(False)
        elif force == "play":
            self.actionPlay.setChecked(True)

        if self.actionPlay.isChecked():
            ui_util.setup_icon(self, self.actionPlay, "actionPlay", "media-playback-pause")
            self.PlaySignal.emit(timeline_length_int)

        else:
            ui_util.setup_icon(self, self.actionPlay, "actionPlay")  # to default
            self.PauseSignal.emit()

    def actionAddTrack_trigger(self, event):
        log.info("actionAddTrack_trigger")

        self.addTrack("test-action")

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

    def cut(self, key, current_frame, color):
        log.info("add cut %s,%s, %s", key, current_frame, color)

        '''
        layerid = -1;
        layers = get_app().project.get(["layers"])
        if (len(layers) == 0):  # add first track if no
            layerid = self.addTrack("track_test_auto").data["id"]
        else:
            layerid = layers[0].data["id"]
        '''

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

    def keyPressEvent(self, event):
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
        if color:
            self.cut(key.toString(), self.preview_thread.current_frame, color)
        elif key.matches(self.getShortcutByName("actionAddTrack")) == QKeySequence.ExactMatch:
            self.addTrack("track_test")

    def getShortcutByName(self, setting_name):
        """ Get a key sequence back from the setting name """
        s = settings.get_settings()
        shortcut = QKeySequence(s.get(setting_name))
        return shortcut

    def getColorByName(self, setting_name):
        """ Get a key sequence back from the setting name """
        s = settings.get_settings()
        return s.get(setting_name)


    def previewFrame(self, position_frames):
        """Preview a specific frame"""
        # Notify preview thread
        self.previewFrameSignal.emit(position_frames)
