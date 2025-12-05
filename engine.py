import simpy
import numpy as np
import numpy.random as rand
import logging
import copy

logging.basicConfig(level=logging.DEBUG, format='%(message)s')
log = logging.getLogger('StochasticGame')

class Event:
    def __init__(self, piece, msg, time, pieces):
        self.piece = piece
        self.msg = msg
        self.time = time
        self.pieces = pieces
        self.object_type = type(self.piece).__name__
        log.debug(f'[{self.time:.2f}]: {self.object_type} {self.piece.id} {self.msg}')
    def __str__(self):
        return f"[{self.time:.2f}]: {self.object_type} {self.piece.id} {self.msg}"
    def __repr__(self):
        return f"[{self.time:.2f}]: {self.object_type} {self.piece.id} {self.msg}"

class Piece:
    def __init__(self, id, posx, posy, game):
        self.id = id
        self.posx = posx
        self.posy = posy
        self.game = game
        self.active = True
        self.env = game.env if game is not None else None
        self.runnable = False
    def get_pos(self):
        return (self.posx, self.posy)
    def move(self, dx, dy):
        self.posx += dx
        self.posy += dy

class Target(Piece):
    def __init__(self, id, posx, posy, game, points):
        super().__init__(id, posx, posy, game)
        self.points = points

    def hit(self):
        self.active = False
        self.game.event(self, 'destroyed')
        self.game.points += self.points
        log.debug(f'[{self.game.env.now:.2f}]: {self.points} points gained, {self.game.points}/{self.game.possible_points} possible points earned')

class RWTarget(Target):
    def __init__(self, id, posx, posy, game, points, speed):
        super().__init__(id, posx, posy, game, points)
        self.points = points
        self.speed = speed
        self.runnable = True
    
    def move(self):
        while self.active:
            try:
                yield self.env.timeout(self.speed)
            except simpy.Interrupt:
                break
            if not self.active:
                break
            direction = rand.randint(0, 3)
            if direction == 0:
                self.posx += 1
            elif direction == 1:
                self.posx -= 1
            elif direction == 2:
                self.posy += 1
            elif direction == 3:
                self.posy -= 1
            if self.posx < -self.game.size:
                self.posx = self.game.size
            if self.posx > self.game.size:
                self.posx = -self.game.size
            if self.posy < -self.game.size:
                self.posy = self.game.size
            if self.posy > self.game.size:
                self.posy = -self.game.size
            self.posy = np.clip(self.posy, -self.game.size, self.game.size)
            self.game.event(self, f'moved to ({self.posx}, {self.posy})')

class Facility:
    def __init__(self, id, rate, game):
        self.id = id
        self.rate = rate
        self.game = game
        self.env = game.env if game is not None else None

    def run(self):
        raise NotImplementedError

    
class Artillery(Facility):
    def run(self):
        while True:
            next = np.random.exponential(1/self.rate)
            try:
                yield self.env.timeout(next)
            except simpy.Interrupt:
                break
            posx, posy = self.game.random_pos()
            self.game.event(self, f'fired at ({posx}, {posy})')
            for p in self.game.pieces:
                if self.game.pieces[p].posx == posx and self.game.pieces[p].posy == posy:
                    if self.game.pieces[p].active:
                        self.game.pieces[p].hit()

class GameEngine:
    def __init__(self, size=100):
        self.env = simpy.Environment()
        self.event_queue = []
        self.size = size
        return
    
    def setup(self, pieces, facilities):
        self.points = 0
        self.pieces = pieces
        self.facilities = facilities
        return

    def run(self):
        self.piece_generators = []
        self.facility_generators = []
        self.possible_points = 0
        for p in self.pieces:
            if self.pieces[p].runnable:
                self.piece_generators.append(self.env.process(self.pieces[p].move()))
            if hasattr(self.pieces[p], 'points'):
                self.possible_points += self.pieces[p].points
        for f in self.facilities:
            self.facility_generators.append(self.env.process(self.facilities[f].run()))
        self.env.process(self.endgame_check())
        log.info(f'Game starting! Total possible points: {self.possible_points}')
        self.env.run(until=100)
        log.info(f'Game ended! Points: {self.points}/{self.possible_points}')

    def endgame_check(self):
        while True:
            active_piece = False
            yield self.env.timeout(1)
            for p in self.pieces:
                if self.pieces[p].active:
                    active_piece = True
                    break
            if not active_piece:
                log.info(f'[{self.env.now:.2f}] All pieces destroyed, ending game')
                for fg in self.facility_generators:
                    fg.interrupt()
                break

    def piece_snapshot(self):
        snap = {}
        for p in self.pieces:
            snap[p] = self.pieces[p].get_pos()
        return snap

    def event(self, piece, msg):
        e = Event(piece, msg, self.env.now, self.piece_snapshot())
        self.event_queue.append(e)
        return
    
    def next_piece_id(self):
        return len(self.pieces) + 1
    
    def random_pos(self):
        return rand.randint(-self.size, self.size), rand.randint(-self.size, self.size)

game = GameEngine(10)
pieces = {}
for i in range(5):
    posx, posy = game.random_pos()
    pieces[i] = RWTarget(i, posx, posy, game, 3*(i+1), i+1)
for i in range(5, 10):
    posx, posy = game.random_pos()
    pieces[i] = Target(i, posx, posy, game, 1)
facilities = {}
for i in range(5):
    facilities[i] = Artillery(i, i+1, game)
game.setup(pieces, facilities)
game.run()
