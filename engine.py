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
    def __str__(self):
        return f"[{self.time}]: Piece {self.piece.id} {self.msg}"
    def __repr__(self):
        return f"[{self.time}]: Piece {self.piece.id} {self.msg}"

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

class StaticTarget(Piece):
    def __init__(self, id, posx, posy, game, points):
        super().__init__(id, posx, posy, game)
        self.points = points

class RWTarget(Piece):
    def __init__(self, id, posx, posy, game, points, speed):
        super().__init__(id, posx, posy, game)
        self.points = points
        self.speed = speed
        self.runnable = True
    
    def move(self):
        while True:
            try:
                yield self.env.timeout(self.speed)
            except simpy.Interrupt:
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

class GameEngine:
    def __init__(self, size=100):
        self.env = simpy.Environment()
        self.event_queue = []
        self.size = size
        return
    
    def setup(self, pieces):
        self.points = 0
        self.pieces = pieces
        return

    def run(self):
        print(self.pieces)
        for p in self.pieces:
            if self.pieces[p].runnable:
                self.env.process(self.pieces[p].move())
        self.env.run(until=100)

    def piece_snapshot(self):
        snap = {}
        for p in self.pieces:
            snap[p] = self.pieces[p].get_pos()
        return snap

    def event(self, piece, msg):
        log.debug(f'[{self.env.now}]: Piece {piece.id} {msg}')
        e = Event(piece, msg, self.env.now, self.piece_snapshot())
        self.event_queue.append(e)
        return

game = GameEngine(10)
pieces = {1: RWTarget(1, 0, 0, game, 10, 5)}
game.setup(pieces)
game.run()
