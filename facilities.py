import simpy
import logging
import numpy as np
import numpy.random as rand
from pieces import Helicopter

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
        self.sim = getattr(game, "simulation_mode", False)

    def run(self):
        raise NotImplementedError
    
    def resource_cost(self):
        raise NotImplementedError
    
    def print_stats(self, log):
        if not self.sim:
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
            if not self.sim:
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
            if not self.sim:
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

            if not self.sim:
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