import sys
import threading
import time
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QTextEdit, QPushButton, QLabel, QFrame, QHBoxLayout
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtWidgets import QLabel
import re
from pieces import Helicopter, Target, RWTarget
from facilities import Artillery, ReconPlane
PLAYBACK_SPEED = 4.0
ARTILLERY_COLOR = "#db3434"
HELICOPTER_COLOR = "#cdd331"
RECON_PLANE_COLOR = "#1818C3"
TARGET_COLOR = "#000000"
RW_TARGET_COLOR = "#666666"
HIT_COLOR ="#25BB00"
EFFECT_PRIORITY = {
    "none": 0,
    "target": 1,
    "rw_target": 1,
    "helicopter": 2,
    "recon": 2,
    "artillery": 3,
    "target_hit": 4,
}


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
        self.last_helicopter_positions = {}
        self.last_rw_target_positions = {}

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
        self.cell_effects = {}

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
        self.targets_hit = 0
    
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
            self.status_label.setText(f"Time: {event.time:.2f}/100\nTargets hit: {self.targets_hit}")
        
        def _extract_and_clamp_coords(msg):
            """
            Extracts coordinates from the message attached to the event.
            """
            m = re.search(r"\((\-?\d+),\s*(\-?\d+)\)", msg)
            if not m:
                return None
            x, y = int(m.group(1)), int(m.group(2))
            gx = max(0, min(x + self.engine_size, self.grid_size - 1))
            gy = max(0, min(y + self.engine_size, self.grid_size - 1))
            return gx, gy
        
        def _clamp_coords(pos):
            x, y = pos
            return max(0, min(x + self.engine_size, self.grid_size - 1)), max(0, min(y + self.engine_size, self.grid_size - 1))
        
        if isinstance(event.piece, Artillery):
            coords = _extract_and_clamp_coords(event.msg)
            if coords:
                gx, gy = coords
                self.apply_cell_effect(
                    gx, gy,
                    "artillery",
                    ARTILLERY_COLOR,
                    int(1000 / PLAYBACK_SPEED)
                )
        
        elif isinstance(event.piece, Helicopter):
            coords = _extract_and_clamp_coords(event.msg)
            if coords:
                gx, gy = coords
                if event.piece.id in self.last_helicopter_positions:
                    lx, ly = self.last_helicopter_positions[event.piece.id]
                    self.remove_cell_effect(lx, ly, "helicopter")
                self.apply_cell_effect(
                    gx, gy,
                    "helicopter",
                    HELICOPTER_COLOR
                )
                self.last_helicopter_positions[event.piece.id] = (gx, gy)

        elif isinstance(event.piece, ReconPlane):
            coords = _extract_and_clamp_coords(event.msg)
            if coords:
                gx, gy = coords
                self.apply_cell_effect(
                    gx, gy,
                    "recon",
                    RECON_PLANE_COLOR,
                    int(1000 / PLAYBACK_SPEED)
                )
        
        elif isinstance(event.piece, Target) or isinstance(event.piece, RWTarget):
            if "destroyed by" in event.msg:
                self.targets_hit += 1
                gx, gy = _clamp_coords(event.piece.get_pos())

                self.apply_cell_effect(
                    gx, gy,
                    "target_hit",
                    HIT_COLOR,
                    int(3000 / PLAYBACK_SPEED)
                )
                if isinstance(event.piece, RWTarget):
                    # Also remove tracking for moving targets
                    if event.piece.id in self.last_rw_target_positions:
                        del self.last_rw_target_positions[event.piece.id]
                    self.remove_cell_effect(gx, gy, "rw_target")
                else:
                    self.remove_cell_effect(gx, gy, "target")
        
        elif type(event) is EndGameEvent:
            overlay_text = f"Game ended! Points: {self.engine.points}/{self.engine.possible_points}\n"
            for f in self.engine.facilities.values():
                if f.active():
                    overlay_text += f"{type(f).__name__} {f.id} earned {f.earned_points} points ({f.earned_points/f.resources:.2f} per resource)\n"

            self.overlay_label.setText(overlay_text)
            self.overlay_label.setVisible(True)
            self.overlay_label.raise_()

        # show active targets
        for p in self.engine.pieces.values():
            if p.active and p.target:
                gx, gy = _clamp_coords(p.get_pos())
                piece_id = p.id
                    
                if isinstance(p, RWTarget):
                    # 1. Clear old position if moved (Only if still tracked)
                    if piece_id in self.last_rw_target_positions:
                        lx, ly = self.last_rw_target_positions[piece_id]
                        if (lx, ly) != (gx, gy):
                            self.remove_cell_effect(lx, ly, "rw_target") 
                    
                    # 2. Apply effect at new position (no duration)
                    self.apply_cell_effect(
                        gx, gy,
                        "rw_target",
                        RW_TARGET_COLOR
                    )
                    # 3. Track new position
                    self.last_rw_target_positions[piece_id] = (gx, gy)

                elif isinstance(p, Target):
                    # Apply effect for static target (no duration)
                    self.apply_cell_effect(
                        gx, gy,
                        "target",
                        TARGET_COLOR
                    )

    def apply_cell_effect(self, gx, gy, effect_name, color, duration_ms=None):
        if (gx, gy) not in self.cell_effects:
            self.cell_effects[(gx, gy)] = {"active": {}, "current": "none"}

        effects = self.cell_effects[(gx, gy)]["active"]
        effects[effect_name] = True

        if EFFECT_PRIORITY[effect_name] >= EFFECT_PRIORITY.get(self.cell_effects[(gx, gy)]["current"], 0):
            self.grid_cells[gy][gx].setStyleSheet(f"background-color: {color}; border: 1px solid gray;")
            self.cell_effects[(gx, gy)]["current"] = effect_name

        if duration_ms is not None:
            QTimer.singleShot(
                duration_ms,
                lambda gx=gx, gy=gy, name=effect_name: self.remove_cell_effect(gx, gy, name)
            )
    
    def remove_cell_effect(self, gx, gy, effect_name):
        cell = self.cell_effects[(gx, gy)]
        cell["active"][effect_name] = False

        # Find highest remaining effect
        remaining = [name for name, active in cell["active"].items() if active]

        if not remaining:
            # revert to white
            self.grid_cells[gy][gx].setStyleSheet("background-color: white; border: 1px solid gray;")
            cell["current"] = "none"
            return

        # Pick highest-priority effect
        best = max(remaining, key=lambda n: EFFECT_PRIORITY[n])
        cell["current"] = best

        # Re-apply correct color
        if best == "target_hit":
            color = HIT_COLOR
        elif best == "artillery":
            color = ARTILLERY_COLOR
        elif best == "helicopter":
            color = HELICOPTER_COLOR
        elif best == "recon":
            color = RECON_PLANE_COLOR
        elif best == "rw_target":
            color = RW_TARGET_COLOR
        elif best == "target":
            color = TARGET_COLOR
        else:
            color = "white"

        self.grid_cells[gy][gx].setStyleSheet(f"background-color: {color}; border: 1px solid gray;")

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