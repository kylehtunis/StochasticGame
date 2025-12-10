import simpy
import numpy as np
import numpy.random as rand
import logging

############# Piece Classes #############

class Piece:
    """
    A Piece is an entity that exists on the game board.
    Pieces which are targets can be hit by attacks and destroyed.
    Pieces which are runnable are generators which can be scheduled to run and perform some action, such as moving.
    """
    def __init__(self, id, posx, posy, game):
        self.id = id
        self.posx = posx
        self.posy = posy
        self.game = game
        self.active = True
        self.env = game.env if game is not None else None
        self.runnable = False
        self.target = False
    def get_pos(self):
        return (self.posx, self.posy)
    
    def run(self):
        raise NotImplementedError

class Target(Piece):
    """
    A Target is a piece that can be hit by attacks and destroyed, granting points.
    """
    def __init__(self, id, posx, posy, game, points):
        super().__init__(id, posx, posy, game)
        self.points = points
        self.target = True

    def hit(self, attacker, log):
        """
        This function is called when the Target is hit by an attack.
        """
        self.active = False
        self.game.points += self.points
        if not self.game.simulation_mode:
            self.game.event(self, f'destroyed by {type(attacker).__name__} {attacker.id}', level=logging.INFO)
            log.debug(f'[{self.game.env.now:.2f}]: {self.points} points gained, {self.game.points}/{self.game.possible_points} possible points earned')

class RWTarget(Target):
    """
    A RWTarget is a Target that moves around the map according to a random walk.
    """
    def __init__(self, id, posx, posy, game, points, speed):
        super().__init__(id, posx, posy, game, points)
        self.points = points
        self.speed = speed
        self.runnable = True
    
    def run(self):
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
            self.posx, self.posy = self.game.wrap_pos(self.posx, self.posy)
            if not self.game.simulation_mode:
                self.game.event(self, f'moved to ({self.posx}, {self.posy})')

class Helicopter(Piece):
    """
    A helicopter that moves around the map according to a Levy flight, destroying targets it lands on.
    """
    def __init__(self, id, posx, posy, game, alpha, speed, parent):
        super().__init__(id, posx, posy, game)
        self.active = True
        self.runnable = True
        self.alpha = alpha
        self.speed = speed
        self.parent = parent

    def run(self):
        while self.active:
            try:
                yield self.env.timeout(self.speed)
            except simpy.Interrupt:
                break
            if not self.active:
                break
            angle = rand.uniform(0, 2 * np.pi)
            length = L = rand.uniform(0.0001, 1.0)**(-1.0 / self.alpha)
            j_x_float = L * np.cos(angle)
            j_y_float = L * np.sin(angle)
            j_x = int(np.round(j_x_float))
            j_y = int(np.round(j_y_float))
            self.posx, self.posy = self.game.wrap_pos(self.posx + j_x, self.posy + j_y)
            if not self.game.simulation_mode:
                self.game.event(self, f'moved to ({self.posx}, {self.posy})')
            self.parent.earned_points += self.game.attack_pos(self, self.posx, self.posy)