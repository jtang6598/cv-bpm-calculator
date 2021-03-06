import random
from collections import namedtuple

import numpy as np
from scipy.optimize import curve_fit

from dataprocessor.math_utils import *
from dataprocessor.smoothing import BaseSmoother
from dataprocessor.smoothing import DoubleExponential

Fit = namedtuple('Fit', ['params', 'error', 'time', 'data'])


class BPMCalc:

    def __init__(self, smoother: BaseSmoother = None):
        self.smoother = smoother
        if not self.smoother:
            self.smoother = DoubleExponential()
        self.time = []
        self.data = []
        self.minimum_points = 10
        self.maximum_points = 5000
        self.fit = None

    def reset(self):
        self.data = []
        self.time = []
        self.fit = None

    def send_data(self, time, coord):
        if len(self.time) == 0 or self.time[-1] != time:
            self.data.append(coord)
            self.time.append(time)

    def calculate_bpm(self):
        if len(self.time) < self.minimum_points:
            return None

        if len(self.time) > self.maximum_points:
            self.time = self.time[-self.maximum_points:]
            self.data = self.data[-self.maximum_points:]

        new_fit = self.optimum_fit(self.time, self.data)
        # only change fit if error on the frequency parmeter improves
        if not self.fit or new_fit.error < self.fit.error:
            self.fit = new_fit

        return self.bpm_from_ang_freq(self.fit[0][1])

    def optimum_fit(self, time, data):
        """
        Calculate optimum sine fit of either velocity along an average position axis ("bop vector") or of y-velocity
        position data (whichever is best) by sampling random chunks of the data.
        :param time: All times recorded
        :param data: All raw position data recorded
        :return: Tuple containing (fit params, total squared error of fit, sample time, sample processed velocity)
        """

        samples = self.generate_samples(time, data, 1, len(data)) \
            if len(data) < 50 \
            else self.generate_samples(time, data, 10)
        optimum_sample = None

        # initial guess -- amplitude 50, 116bpm (avg pop song), phase shift 1 rad, 0 vertical offset
        p0 = [50, 2 * np.pi * 116 / 60, 1, 0] if self.fit is None else self.fit[0]

        for sample in samples:
            sample[1] = self.smoother.smooth(sample[1])
            sample_fit = self.find_fit(sample, p0)
            if not optimum_sample or (sample_fit and sample_fit.error < optimum_sample.error):
                optimum_sample = sample_fit

        return optimum_sample

    def find_fit(self, sample, p0):
        try:
            # fit both velocity along bop axis or y velocity, whichever is best
            velocity_data = (self.bop_vector_velocity(*sample), clean_data(derivative(*sample)[:, 1]))
            popt, pcov = [None] * 2, [None] * 2
            for i, data in enumerate(velocity_data):
                popt[i], pcov[i] = curve_fit(sinfunc, sample[0][1: -1],
                                             self.smoother.smooth(data)[1: -1], p0=p0)
            # minimize error in frequency parameter
            min_index = 0 if np.diag(pcov[1] - pcov[0])[1] > 0 else 1
            return Fit(popt[min_index], np.diag(pcov[min_index])[1], sample[0], velocity_data[min_index])
        except RuntimeError:  # raised when optimum fit parameters aren't found
            pass

    def set_frequency(self, frequency):
        self.fit[0][1] = 2 * np.pi * frequency

    def bop_vector_velocity(self, time, data):
        head_velocity = derivative(time, data)
        bop_vector = self.lsrl_vector(data)
        head_velocity = self.project_velocities(head_velocity, bop_vector)
        return clean_data(head_velocity)

    @staticmethod
    def project_velocities(data, direction):
        elt_wise_product = data * direction
        dots = np.array([sum(product) for product in elt_wise_product])
        projections = dots / np.linalg.norm(direction)
        return projections

    @staticmethod
    def generate_samples(time, data, num_chunks, chunk_length=50):
        for _ in range(num_chunks):
            i = random.randint(0, len(data) - chunk_length)
            yield [np.array(time[i: i + chunk_length]), np.array([*data[i: i + chunk_length]])]

    @staticmethod
    def lsrl_vector(data):
        A = np.array([data[:, 0], np.ones(len(data))]).T
        m, _ = np.linalg.lstsq(A, data[:, 1], rcond=None)[0]
        mag = np.sqrt(1 + m ** 2)
        return np.array([np.sign(m) / mag, np.abs(m) / mag])  # want positive y to be positive in this axis

    @staticmethod
    def bpm_from_ang_freq(angular_frequency):
        freq = np.abs(angular_frequency) / (2 * np.pi)
        return freq * 60
