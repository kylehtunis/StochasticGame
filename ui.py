import sys
import threading
import time
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QTextEdit, QPushButton, QLabel, QFrame, QHBoxLayout
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtWidgets import QLabel
import re
from pieces import Helicopter
from facilities import Artillery, ReconPlane
PLAYBACK_SPEED = 4.0
ARTILLERY_COLOR = "#db3434"
HELICOPTER_COLOR = "#2c3e50"
RECON_PLANE_COLOR = "#775814"

class EventBridge(QObject):
    event_signal = Signal(object)

    def __init__(self):
        super().__init__()

    def push_event(self, event):
        self.event_signal.emit(event)
    
class EndGameEvent:
    """Event sent to UI when the game ends."""
    def __init__(self, engine):
        self.engine = engine
        self.time = engine.env.now
        self.msg = "all targets destroyed"
        self.piece = None
        self.object_type = "System"


ui_event_bridge = EventBridge()


class SimpleMessage:
    def __init__(self, msg):
        self.time = time.time()
        self.msg = msg
        self.object_type = "System"
        self.piece = type("X", (), {"id": "-"})()

    def __str__(self):
        return f"[{self.time:.2f}] SYSTEM {self.msg}"


class GameViewer(QWidget):
    def __init__(self, engine):
        super().__init__()
        self.setWindowTitle("Stochastic Game — Real-Time Event Viewer")
        self.setGeometry(200, 200, 700, 700)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.engine = engine
        self.engine_size = engine.size

        layout = QVBoxLayout()
        self.status_label = QLabel("Waiting for game to begin...")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        # -------- Grid setup --------
        self.grid_size = self.engine_size * 2 + 1
        self.cell_size = max(1, min(25, 500 // self.grid_size)) 
        self.grid_frame = QFrame()
        self.grid_frame.setFixedSize(self.grid_size*self.cell_size, self.grid_size*self.cell_size)
        self.grid_frame.setStyleSheet("background-color: white;")
        grid_container = QHBoxLayout()
        grid_container.addStretch()
        grid_container.addWidget(self.grid_frame)
        grid_container.addStretch()
        layout.addLayout(grid_container)
        self.last_positions = {}

        # Create cells
        self.grid_cells = []
        for y in range(self.grid_size):
            row = []
            for x in range(self.grid_size):
                cell = QLabel(self.grid_frame)
                cell.setFixedSize(self.cell_size, self.cell_size)
                cell.setStyleSheet("background-color: white; border: 1px solid gray;")
                cell.move(x*self.cell_size, y*self.cell_size)
                row.append(cell)
            self.grid_cells.append(row)

        # -------- Event log --------
        self.text_box = QTextEdit()
        self.text_box.setReadOnly(True)
        self.text_box.setFixedHeight(200)  # smaller height at bottom
        layout.addWidget(self.text_box)

        self.overlay_label = QLabel(self.grid_frame)  # make it a child of grid_frame
        self.overlay_label.setAlignment(Qt.AlignCenter)
        self.overlay_label.setStyleSheet("""
            background-color: rgba(0, 0, 0, 180);
            color: white;
            font-size: 18px;
            padding: 10px;
        """)
        self.overlay_label.setVisible(False)
        self.overlay_label.setWordWrap(True)  # allow multi-line text

        # Set initial size to cover the grid
        self.overlay_label.setFixedSize(self.grid_frame.width(), self.grid_frame.height())
        self.overlay_label.move(0, 0)  # top-left of grid_frame
        self.overlay_label.raise_()

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        layout.addWidget(self.close_button)
        self.setLayout(layout)

        # Event queue and signal
        ui_event_bridge.event_signal.connect(self.queue_event)
        self.event_queue = []
        self.start_time = None

        # Timer to periodically check queue
        self.timer = self.startTimer(50)  # 50 ms
    
    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Keep overlay covering the grid
        self.overlay_label.setFixedSize(self.grid_frame.width(), self.grid_frame.height())
        self.overlay_label.move(0, 0)

    def queue_event(self, event):
        """Receive an event from the engine and queue it for timed display."""
        self.event_queue.append(event)
        if self.start_time is None:
            self.start_time = time.time()

    def timerEvent(self, event):
        """Display queued events according to their timestamp and playback speed."""
        if not self.event_queue or self.start_time is None:
            return

        elapsed = (time.time() - self.start_time) * PLAYBACK_SPEED
        to_display = [e for e in self.event_queue if e.time <= elapsed]

        for e in to_display:
            self.display_event(e)
            self.event_queue.remove(e)

    def display_event(self, event):
        """Append an event to the text box and update the grid if needed."""
        if type(event) is not EndGameEvent:
            self.text_box.append(str(event))
            self.text_box.verticalScrollBar().setValue(
                self.text_box.verticalScrollBar().maximum()
            )
            self.status_label.setText(f"Simulation time: {event.time:.2f}")

        if isinstance(event.piece, Artillery):
            m = re.search(r"\((\-?\d+),\s*(\-?\d+)\)", event.msg)
            if m:
                x, y = int(m.group(1)), int(m.group(2))
                gx = x + self.engine_size
                gy = y + self.engine_size
                gx = max(0, min(gx, self.grid_size - 1))
                gy = max(0, min(gy, self.grid_size - 1))
                self.grid_cells[gy][gx].setStyleSheet(f"background-color: {ARTILLERY_COLOR}; border: 1px solid gray;")
                # Reset color after 0.25s (scaled by PLAYBACK_SPEED)
                QTimer.singleShot(int(250/PLAYBACK_SPEED),
                                  lambda gx=gx, gy=gy: self.grid_cells[gy][gx].setStyleSheet(
                                      "background-color: white; border: 1px solid gray;"
                                  ))
        
        if isinstance(event.piece, Helicopter):
            m = re.search(r"\((\-?\d+),\s*(\-?\d+)\)", event.msg)
            # Get grid coordinates
            if m:
                x, y = int(m.group(1)), int(m.group(2))
                gx = x + self.engine_size
                gy = y + self.engine_size
                gx = max(0, min(gx, self.grid_size - 1))
                gy = max(0, min(gy, self.grid_size - 1))
                
                if event.piece.id in self.last_positions:
                    lx, ly = self.last_positions[event.piece.id]
                    self.grid_cells[ly][lx].setStyleSheet("background-color: white; border: 1px solid gray;")
                self.grid_cells[gy][gx].setStyleSheet(f"background-color: {HELICOPTER_COLOR}; border: 1px solid gray;")
                self.last_positions[event.piece.id] = (gx, gy)

        if isinstance(event.piece, ReconPlane):
            m = re.search(r"\((\-?\d+),\s*(\-?\d+)\)", event.msg)
            if m:
                x, y = int(m.group(1)), int(m.group(2))
                gx = x + self.engine_size
                gy = y + self.engine_size
                gx = max(0, min(gx, self.grid_size - 1))
                gy = max(0, min(gy, self.grid_size - 1))
                self.grid_cells[gy][gx].setStyleSheet(f"background-color: {RECON_PLANE_COLOR}; border: 1px solid gray;")
                # Reset color after 0.25s (scaled by PLAYBACK_SPEED)
                QTimer.singleShot(int(1000/PLAYBACK_SPEED),
                                  lambda gx=gx, gy=gy: self.grid_cells[gy][gx].setStyleSheet(
                                      "background-color: white; border: 1px solid gray;"
                                  ))
        
        if type(event) is EndGameEvent:
            overlay_text = f"Game ended! Points: {self.engine.points}/{self.engine.possible_points}\n"
            for f in self.engine.facilities.values():
                if f.active():
                    overlay_text += f"{type(f).__name__} {f.id} earned {f.earned_points} points ({f.earned_points/f.resources:.2f} per resource)\n"

            self.overlay_label.setText(overlay_text)
            self.overlay_label.setVisible(True)
            self.overlay_label.raise_()

    def start_game(self, engine):
        """Run the simulation in a background thread."""
        thread = threading.Thread(target=engine.run, daemon=True)
        thread.start()


def launch_gui(engine):
    app = QApplication(sys.argv)
    viewer = GameViewer(engine=engine)
    viewer.show()
    viewer.start_game(engine)
    sys.exit(app.exec())