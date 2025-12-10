import simpy
import numpy as np
import numpy.random as rand
import logging
import sys
import ui
from facilities import Helipad, Artillery, ReconPlane
from pieces import RWTarget, Target

loglevel = logging.INFO
if len(sys.argv) > 1 and '-v' in sys.argv:
    loglevel = logging.DEBUG
    print("Verbose logging enabled")

logging.basicConfig(level=loglevel, format='%(message)s')
log = logging.getLogger('StochasticGame')


############# Helper Classes #############

class Event:
    """
    An Event is anything that happens in the game. It is logged to the console and stored in the event queue.
    """
    def __init__(self, piece, msg, time, pieces, logger=log.debug):
        self.piece = piece
        self.msg = msg
        self.time = time
        self.pieces = pieces
        self.object_type = type(self.piece).__name__
        output = f'[{self.time:.2f}]: {self.object_type} {self.piece.id} {self.msg}'
        logger(output)
    def __str__(self):
        return f"[{self.time:.2f}]: {self.object_type} {self.piece.id} {self.msg}"
    def __repr__(self):
        return f"[{self.time:.2f}]: {self.object_type} {self.piece.id} {self.msg}"

            

############# GameEngine #############

class GameEngine:
    """
    GameEngine is the main class responsible for running the game. It is responsible for managing the event queue, scheduling generators, and running the simulation.
    """
    def __init__(self, size=100, resource_limit=100, real_time=False):
        self.env = simpy.rt.RealtimeEnvironment(strict=False) if real_time else simpy.Environment()
        self.event_queue = []
        self.size = size
        self.width = size * 2
        self.resource_limit = resource_limit
        self.next_piece = 1
        self.piece_generators = []
        self.facility_generators = []
        self.possible_points = 0
        return
    
    def setup(self, pieces, facilities):
        """
        Called before the game is run. This function sets up the game by adding the Pieces and Facilities to the game.
        """
        self.points = 0
        self.pieces = pieces
        for p in self.pieces.values():
            if p.runnable:
                self.piece_generators.append(self.env.process(p.run()))
        self.facilities = facilities
        self.set_up = True
        return
    
    def add_piece(self, piece):
        """
        Adds a Piece to the game
        """
        if piece.id in self.pieces:
            raise ValueError(f'Piece with id {piece.id} already exists')
        self.pieces[piece.id] = piece
        if piece.runnable:
            self.piece_generators.append(self.env.process(piece.run()))

    def run(self):
        """
        Start the simulation. This function schedules the Piece and Facility generators and runs the simulation until the game ends.
        """
        if not self.set_up:
            raise RuntimeError("GameEngine.setup() must be called before GameEngine.run()")
        total_cost = 0
        total_cost = sum(f.resources for f in self.facilities.values())
        if total_cost > self.resource_limit:
            raise ValueError(f'Total resource cost ({total_cost}) exceeds resource limit ({self.resource_limit})')
        print(f'Resources used: {total_cost}/{self.resource_limit}')
        for p in self.pieces:
            if hasattr(self.pieces[p], 'points'):
                self.possible_points += self.pieces[p].points
        for f in self.facilities:
            if self.facilities[f].active():
                self.facility_generators.append(self.env.process(self.facilities[f].run()))
        self.env.process(self.endgame_check())
        log.info(f'Game starting! Total possible points: {self.possible_points}')
        self.env.run(until=100)
        ui.ui_event_bridge.push_event(ui.EndGameEvent(self))
        log.info(f'Game ended! Points: {self.points}/{self.possible_points}')
        for f in self.facilities.values():
            if f.active():
                f.print_stats(log)

    def endgame_check(self):
        """
        Ends the game if all Targets have been destroyed.
        """
        while True:
            active_target = False
            yield self.env.timeout(1)
            for p in self.pieces.values():
                if p.target and p.active:
                    active_target = True
                    break
            if not active_target:
                log.info(f'[{self.env.now:.2f}] All targets destroyed, ending game')
                ui.ui_event_bridge.push_event(ui.EndGameEvent(self))
                for fg in self.facility_generators:
                    fg.interrupt()
                for p in self.piece_generators:
                    p.interrupt()
                break

    def piece_snapshot(self):
        """
        Creates a snapshot of the current state of the game. This is used to log events.
        """
        snap = {}
        for p in self.pieces:
            snap[p] = self.pieces[p].get_pos()
        return snap

    def event(self, obj, msg, level=logging.DEBUG):
        """
        Log an event to the console and the event queue.
        """
        logger = log.debug if level == logging.DEBUG else log.info
        e = Event(obj, msg, self.env.now, self.piece_snapshot(), logger)
        self.event_queue.append(e)
        ui.ui_event_bridge.push_event(e)
        return
    
    def next_piece_id(self):
        """
        Get the next available piece ID.
        """
        self.next_piece += 1
        return self.next_piece - 1
    
    def random_pos(self):
        """
        Returns a random position within the game board.
        """
        return rand.randint(-self.size, self.size), rand.randint(-self.size, self.size)
    
    def wrap_pos(self, posx, posy):
        """
        Ensures that the position is within the game board. If it is not, it wraps it around the board (Pac-Man style).
        """
        new_posx = ((posx + self.size) % (self.width) + self.width) % self.width - self.size
        new_posy = ((posy + self.size) % (self.width) + self.width) % self.width - self.size
        return new_posx, new_posy
    
    def attack_pos(self, attacker, posx, posy):
        """
        Check if a position is a target and if so, hit it.
        """
        earned_points = 0
        for p in self.pieces:
            if self.pieces[p].posx == posx and self.pieces[p].posy == posy:
                if self.pieces[p].active and self.pieces[p].target:
                    self.pieces[p].hit(attacker, log)
                    earned_points += self.pieces[p].points
        return earned_points
    

############# Main #############

rt = False
if len(sys.argv) > 1 and '-rt' in sys.argv:
    rt = True
    print("Realtime simulation enabled")

difficulty = input("How difficult do you want the game to be? Choose 1 for easy, 2 for hard.\n> ")
difficulty = int(difficulty)
while difficulty != 1 and difficulty != 2:
    print("Invalid input, choose 1 or 2.")
    difficulty = input("How difficult do you want the game to be? Choose 1 for easy, 2 for hard.\n> ")
    difficulty = int(difficulty)
game = GameEngine(difficulty * 20, 50, rt)
facility_count = 3
print(f"You have {game.resource_limit} resources to spend, split between {facility_count} facilities.")
artillery_resources = input("How many resources do you want to spend on artillery?\n> ")
artillery_resources = int(artillery_resources)
while artillery_resources > 50:
    print("Invalid input, exceeded 50.")
    print(f"Resources left: 50.")
    artillery_resources = input("How many resources do you want to spend on artillery?\n> ")
    artillery_resources = int(artillery_resources)
total = artillery_resources
print(f"Resources left: {50 - total}.")
helipad_resources = input("How many resources do you want to spend on the helipad?\n> ")
helipad_resources = int(helipad_resources)
while total + helipad_resources > 50:
    print("Invalid input, exceeded 50.")
    print(f"Resources left: {50 - total}.")
    helipad_resources = input("How many resources do you want to spend on the helipad?\n> ")
    helipad_resources = int(helipad_resources)
total += helipad_resources
print(f"Resources left: {50 - total}.")
recon_resources = input("How many resources do you want to spend on the recon plane?\n> ") # DAVID CODE
recon_resources = int(recon_resources) # DAVID CODE
while total + recon_resources > 50:
    print("Invalid input, exceeded 50.")
    print(f"Resources left: {50 - total}.")
    recon_resources = input("How many resources do you want to spend on the recon plane?\n> ")
    recon_resources = int(recon_resources)
pieces = {}
for speed, i in enumerate(range(100000, 100010)):
    posx, posy = game.random_pos()
    pieces[i] = RWTarget(i, posx, posy, game, 5, speed+1)
for i in range(100010, 100060):
    posx, posy = game.random_pos()
    pieces[i] = Target(i, posx, posy, game, 1)
facilities = {}
facilities[1] = Artillery(1, artillery_resources, game)
facilities[2] = Helipad(2, helipad_resources, game, 0.5)
facilities[3] = ReconPlane(3, recon_resources, game=game, n_strata=11-(5-difficulty)*2) # DAVID CODE
game.setup(pieces, facilities)
ui.launch_gui(game)
