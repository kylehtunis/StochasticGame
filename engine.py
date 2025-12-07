import simpy
import numpy as np
import numpy.random as rand
import logging
import sys

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

    def hit(self, attacker):
        """
        This function is called when the Target is hit by an attack.
        """
        self.active = False
        self.game.event(self, f'destroyed by {type(attacker).__name__} {attacker.id}', level=logging.INFO)
        self.game.points += self.points
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
            self.game.event(self, f'moved to ({self.posx}, {self.posy})')
            self.parent.earned_points += self.game.attack_pos(self, self.posx, self.posy)


############# Facility Classes #############

class Facility:
    """
    A Facility is a player-owned entitiy that performs some action, such as attacking positions or swpawinging player-owned pieces.
    Facilities require resources. The more resources a facility has, the more frequently it will perform its action.
    Facilities that have no resources are inactive and are not scheduled to run.
    """
    def __init__(self, id, resources, game):
        self.id = id
        self.resources = resources
        self.game = game
        self.env = game.env if game is not None else None
        self.earned_points = 0

    def run(self):
        raise NotImplementedError
    
    def resource_cost(self):
        raise NotImplementedError
    
    def print_stats(self):
        log.info(f'{type(self).__name__} {self.id} earned {self.earned_points} points ({self.earned_points/self.resources} per resource)')

    def active(self):
        return self.resources > 0

    
class Artillery(Facility):
    """
    The Artillery is a Facility that fires at targets according to a Poisson process. One resource buys an expecation of one shot per time.
    """
    def __init__(self, id, resources, game):
        super().__init__(id, resources, game)
        self.rate = resources

    def run(self):
        while True:
            next = np.random.exponential(1/self.rate)
            try:
                yield self.env.timeout(next)
            except simpy.Interrupt:
                break
            posx, posy = self.game.random_pos()
            self.game.event(self, f'fired at ({posx}, {posy})')
            self.earned_points += self.game.attack_pos(self, posx, posy)

            # Antithetic variate: DAVID CODE
            ax = -posx
            ay = -posy
            self.game.event(self, f'fired (antithetic) at ({ax}, {ay})')
            self.earned_points += self.game.attack_pos(self, ax, ay)

    def resource_cost(self):
        return self.rate


class Helipad(Facility):
    """
    The Helipad is a Facility that spawns Helicopters according to a Poisson process. One resource buys an expecation of one helicopter per 0.025 time.
    """
    def __init__(self, id, resources, game, alpha):
        super().__init__(id, resources, game)
        self._RESOURCE_MULTIPLIER = 0.025
        self.rate = resources * self._RESOURCE_MULTIPLIER
        if not 0 < alpha <= 2:
            raise ValueError("Lévy exponent 'alpha' must be between 0 and 2.")
        self.alpha = alpha

    def run(self):
        while True:
            next = np.random.exponential(1/self.rate)
            try:
                yield self.env.timeout(next)
            except simpy.Interrupt:
                break
            posx, posy = self.game.random_pos()
            id = self.game.next_piece_id()
            h = Helicopter(id, posx, posy, self.game, self.alpha, 1, self)
            self.game.add_piece(h)
            self.game.event(self, f'spawned Helicopter {id} at ({posx}, {posy})', level=logging.INFO)

class ReconPlane(Facility): #DAVID CODE
    """
    ReconPlane scans the map in horizontal bands (strata).
    Each scan chooses the next band in a round-robin way and
    destroys any targets in that band.
    This demonstrates stratified sampling over the y-coordinate.
    """
    def __init__(self, id, resources, game, n_strata=4):
        super().__init__(id, resources, game)
        self._RESOURCE_MULTIPLIER = 0.02
        self.rate = 1
        self.sample_rate = resources * self._RESOURCE_MULTIPLIER
        self.n_strata = n_strata
        self.current_stratum = 0

    def run(self):
        """
        Run the ReconPlane facility. Scans happen according to a Poisson process.
        Each scan hits all targets in the selected horizontal band.
        """
       
        while True:
            next_t = np.random.exponential(1 / self.rate)
            try:
                yield self.env.timeout(next_t)
            except simpy.Interrupt:
                break

            band_height = int((2 * self.game.size) / self.n_strata)
            s = self.current_stratum
            self.current_stratum = (self.current_stratum + 1) % self.n_strata

            y_min = -self.game.size + s * band_height
            y_max = y_min + band_height

            scan_y = rand.randint(int(y_min), int(y_max) + 1)

            self.game.event(
                self,
                f'began scanning horizontal band y={scan_y}',
                level=logging.INFO
            )

            for i in range(-self.game.size, self.game.size + 1):
                r = rand.uniform(0, 1)
                if r < self.sample_rate:
                    self.game.event(self, f'attacked ({i}, {scan_y})')
                    self.earned_points += self.game.attack_pos(self, i, scan_y)

            

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
        return
    
    def setup(self, pieces, facilities):
        """
        Called before the game is run. This function sets up the game by adding the Pieces and Facilities to the game.
        """
        self.points = 0
        self.pieces = pieces
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
        self.piece_generators = []
        self.facility_generators = []
        self.possible_points = 0
        total_cost = 0
        total_cost = sum(f.resources for f in self.facilities.values())
        if total_cost > self.resource_limit:
            raise ValueError(f'Total resource cost ({total_cost}) exceeds resource limit ({self.resource_limit})')
        print(f'Resources used: {total_cost}/{self.resource_limit}')
        for p in self.pieces:
            if self.pieces[p].runnable:
                self.piece_generators.append(self.env.process(self.pieces[p].run()))
            if hasattr(self.pieces[p], 'points'):
                self.possible_points += self.pieces[p].points
        for f in self.facilities:
            if self.facilities[f].active():
                self.facility_generators.append(self.env.process(self.facilities[f].run()))
        self.env.process(self.endgame_check())
        log.info(f'Game starting! Total possible points: {self.possible_points}')
        self.env.run(until=100)
        log.info(f'Game ended! Points: {self.points}/{self.possible_points}')
        for f in self.facilities.values():
            if f.active():
                f.print_stats()

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
                    self.pieces[p].hit(attacker)
                    earned_points += self.pieces[p].points
        return earned_points
    

############# Main #############

rt = False
if len(sys.argv) > 1 and '-rt' in sys.argv:
    rt = True
    print("Realtime simulation enabled")

difficulty = input("How difficult do you want the game to be, on a scale of 1 to 5?\n> ")
difficulty = int(difficulty)
game = GameEngine(difficulty * 20, 50, rt)
facility_count = 3
print(f"You have {game.resource_limit} resources to spend, split between {facility_count} facilities.")
artillery_resources = input("How many resources do you want to spend on artillery?\n> ")
artillery_resources = int(artillery_resources)
helipad_resources = input("How many resources do you want to spend on the helipad?\n> ")
helipad_resources = int(helipad_resources)
recon_resources = input("How many resources do you want to spend on the recon plane?\n> ") # DAVID CODE
recon_resources = int(recon_resources) # DAVID CODE
pieces = {}
for i in range(100000, 100010):
    posx, posy = game.random_pos()
    pieces[i] = RWTarget(i, posx, posy, game, 5, i+1)
for i in range(100010, 100060):
    posx, posy = game.random_pos()
    pieces[i] = Target(i, posx, posy, game, 1)
facilities = {}
facilities[1] = Artillery(1, artillery_resources, game)
facilities[2] = Helipad(2, helipad_resources, game, 0.5)
facilities[3] = ReconPlane(3, recon_resources, game=game, n_strata=11-(5-difficulty)*2) # DAVID CODE
game.setup(pieces, facilities)
game.run()
