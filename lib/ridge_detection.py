# -*- coding: utf-8 -*-
"""
Created on Thu Mar 12 22:24:55 2015

@author: benamy
"""

# -*- coding: utf-8 -*-
"""
Created on Wed Feb 11 18:20:36 2015

@author: benamy
"""

from lib.timer import timeStart, timeEnd
from lib.debug import Debug, pad

import numpy as np
from math import log
from scipy import ndimage
from scipy.ndimage.filters import gaussian_filter1d, gaussian_laplace
from skimage.feature import peak_local_max
from skimage.filters import threshold_otsu
from skimage.morphology import remove_small_objects

from lib.utilities import normalize

def get_ridge_region_vert(ridges, shape):
  '''
  '''
  ridge_region = np.zeros(shape, dtype=float)

  for row, col, sigma, max_value in ridges:
    ridge_width = round(np.sqrt(2) * sigma)
    bounds = np.array([col-ridge_width, col+ridge_width])
    bounds = np.clip(bounds, 0, shape[1]-1)
    ridge_region[row, bounds[0]:bounds[1]] = max_value

  return ridge_region

def get_ridge_region_horiz(ridges, shape):
  '''
  '''
  ridge_region = np.zeros(shape, dtype=float)

  for row, col, sigma, max_value in ridges:
    ridge_width = round(np.sqrt(2) * sigma)
    bounds = np.array([row-ridge_width, row+ridge_width])
    bounds = np.clip(bounds, 0, shape[0]-1)
    ridge_region[bounds[0]:bounds[1], col] = max_value

  return ridge_region

def get_slopes(img, axis):
  abs_sobel = np.abs(ndimage.sobel(img, axis=axis))
  return abs_sobel > threshold_otsu(abs_sobel)

def create_image_cube(img, sigma_list, axis):
  gaussian_blurs = [gaussian_filter1d(img, s, axis=axis) for s in sigma_list]
  num_scales = len(gaussian_blurs) - 1
  image_cube = np.zeros((img.shape[0], img.shape[1], num_scales))
  for i in range(num_scales):
    image_cube[:,:,i] = ((gaussian_blurs[i] - gaussian_blurs[i + 1]))
    Debug.save_image("ridges", "image_cube-" + pad(i), image_cube[:,:,i])
  return image_cube

def create_exclusion_cube(img, image_cube, dark_pixels, convex_pixels,
                          axis, convex_threshold):

  timeStart("get slopes")
  slopes = get_slopes(img, axis=axis)
  timeEnd("get slopes")

  Debug.save_image("ridges", "slopes", slopes)

  exclusion_cube = np.zeros(image_cube.shape, dtype=bool)
  exclusion_cube[:,:,0] = dark_pixels | convex_pixels | slopes \
                        | (image_cube[:,:,0] < -convex_threshold)

  Debug.save_image("ridges", "exclusion_cube_base", exclusion_cube[:,:,0])

  num_scales = image_cube.shape[2]
  for i in range(1, num_scales):
    # each layer of the exclusion cube contains the previous layer
    # plus all convex pixels in the current image_cube layer
    exclusion_cube[:,:,i] = (exclusion_cube[:,:,i-1] \
                            | (image_cube[:,:,i] < -convex_threshold))
    Debug.save_image("ridges", "exclusion_cube-" + pad(i), exclusion_cube[:,:,i])

  return exclusion_cube

def find_valid_maxima(image_cube, footprint, exclusion, low_threshold):
  '''
  Returns a 3D array that is true everywhere that image_cube
  has a local maxima except in regions marked for exclusion.

  '''

  # peak_local_max expects a normalized image (values between 0 and 1)
  normalized_image_cube = normalize(image_cube)

  coordinates = peak_local_max(normalized_image_cube, min_distance=1,
                          threshold_rel=0, threshold_abs=0, exclude_border=True,
                          footprint=footprint)
  maxima = np.zeros_like(normalized_image_cube, dtype=bool)
  if coordinates.size > 0:
      maxima[tuple(coordinates.T)] = True
  return maxima & (~exclusion) & (image_cube >= low_threshold)

def get_convex_pixels(img, convex_threshold):
  laplacian = gaussian_laplace(img, sigma=2)
  Debug.save_image("ridges", "gaussian_laplace", laplacian)
  return laplacian > convex_threshold

def extract_ridge_data(img, sobel_axis, dog_axis, footprint, dark_pixels,
                       convex_pixels, sigma_list, convex_threshold, low_threshold):
  '''
  Returns
  -------
  ridges : 2D boolean array
    True at every pixel considered to be a ridge.
  max_values : 2D float array
    The maximum values across all sigma scales of image_cube.
  max_scales : 2D int array
    The scales at which the image_cube took on those maximum values.

  '''
  num_scales = len(sigma_list) - 1

  timeStart("create difference of gaussian image cube at %s scales" % num_scales)
  image_cube = create_image_cube(img, sigma_list, axis=dog_axis)
  timeEnd("create difference of gaussian image cube at %s scales" % num_scales)

  timeStart("create exclusion cube")
  exclusion = create_exclusion_cube(img,
                                    image_cube=image_cube,
                                    dark_pixels=dark_pixels,
                                    convex_pixels=convex_pixels,
                                    axis=sobel_axis,
                                    convex_threshold=convex_threshold)
  timeEnd("create exclusion cube")

  timeStart("find image cube maxima")
  maxima = find_valid_maxima(image_cube, footprint, exclusion, low_threshold)
  timeEnd("find image cube maxima")

  # set all non-maxima points in image_cube to 0
  timeStart("suppress non-maxima")
  image_cube[~maxima] = 0
  timeEnd("suppress non-maxima")

  timeStart("collapse cubes")
  # ridges is a 2D array that is true everywhere
  # that maxima has at least one true value in any scale
  ridges = np.amax(maxima, axis=-1)
  max_values = np.amax(image_cube, axis=-1)
  max_scales = np.argmax(image_cube, axis=-1)
  timeEnd("collapse cubes")

  return ridges, max_values, max_scales

def compile_ridge_data(sigmas_h, ridges_h, max_values_h):
  indices_h = np.argwhere(ridges_h)
  sigmas_h = sigmas_h[ridges_h][:,np.newaxis]
  max_values_h = max_values_h[ridges_h][:,np.newaxis]
  return np.hstack((indices_h, sigmas_h, max_values_h))

def create_sigma_list(min_sigma, sigma_ratio, scales):
  return min_sigma * np.power(sigma_ratio, scales)

def find_ridges(img, dark_pixels, min_sigma = 0.7071, max_sigma = 30,
            sigma_ratio = 1.9, min_ridge_length = 15,
            low_threshold = 0.002, high_threshold = 0.006,
            convex_threshold = 0.00015, figures=True):
  '''
  The values for min_sigma, max_sigma, and sigma_ratio are hardcoded,
  but they ought to be a function of the scale parameter. They're related
  to the minimum and maximum expected trace width in pixels.

  If max_sigma is too small, the algorithm misses ridges of thick traces.
  Need to do more thinking about how this function works.

  '''
  # num_scales is the number of scales at which to compute a difference of gaussians

  # the following line in words: the number of times you need to multiply
  # min_sigma by sigma_ratio to get max_sigma
  num_scales = int(log(float(max_sigma) / min_sigma, sigma_ratio)) + 1

  # a geometric progression of standard deviations for gaussian kernels
  sigma_list = create_sigma_list(min_sigma, sigma_ratio, np.arange(num_scales + 1))

  # convex_pixels is an image of regions with positive second derivative
  timeStart("get convex pixels")
  convex_pixels = get_convex_pixels(img, convex_threshold)
  timeEnd("get convex pixels")
  
  Debug.save_image("ridges", "convex_pixels", convex_pixels)

  timeStart("find horizontal ridges")
  footprint_h = np.ones((3,1,3), dtype=bool)
  ridges_h, max_values_h, max_scales_h = \
      extract_ridge_data(img, sobel_axis=1, dog_axis=0,
                         footprint=footprint_h, dark_pixels=dark_pixels,
                         convex_pixels=convex_pixels, sigma_list=sigma_list,
                         convex_threshold=convex_threshold, low_threshold=low_threshold)
  timeEnd("find horizontal ridges")

  timeStart("find vertical ridges")
  footprint_v = np.ones((1,3,3), dtype=bool)
  ridges_v, max_values_v, max_scales_v = \
      extract_ridge_data(img, sobel_axis=0, dog_axis=1,
                         footprint=footprint_v, dark_pixels=dark_pixels,
                         convex_pixels=convex_pixels, sigma_list=sigma_list,
                         convex_threshold=convex_threshold, low_threshold=low_threshold)
  timeEnd("find vertical ridges")

  # Horizontal ridges need to be prominent
  ridges_h = ridges_h & (max_values_h >= high_threshold)

  # Vertical ridges need to either be prominent or highly connected
  ridges_v = (ridges_v & ((max_values_v >= high_threshold) |
              remove_small_objects(ridges_v, min_ridge_length,
                         connectivity = 2)))

  timeStart("aggregate information about maxima of horizontal ridges")
  sigmas_h = create_sigma_list(min_sigma, sigma_ratio, max_scales_h)
  ridge_data_h = compile_ridge_data(sigmas_h, ridges_h, max_values_h)
  timeEnd("aggregate information about maxima of horizontal ridges")

  timeStart("prioritize horizontal regions")
  horizontal_regions = get_ridge_region_horiz(ridge_data_h, img.shape)
  ridges_v = ridges_v & (horizontal_regions == 0)
  timeEnd("prioritize horizontal regions")

  Debug.save_image("ridges", "vertical_ridges", ridges_v)
  Debug.save_image("ridges", "horizontal_ridges", ridges_h)

  if figures == True:
    return (ridges_h, ridges_v)
  else:
    # Aggregate information about maxima of vertical ridges
    sigmas_v = create_sigma_list(min_sigma, sigma_ratio, max_scales_v)
    ridge_data_v = compile_ridge_data(sigmas_v, ridges_v, max_values_v)
    return (ridge_data_h, ridge_data_v)
