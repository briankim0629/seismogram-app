# -*- coding: utf-8 -*-
"""
Description:
  Test just meanline and ROI detection, and save some statistics.

Usage:
  pipeline.py --image <filename> --output <directory> [--stats <directory>] [--scale <scale>] [--debug <directory>] [--fix-seed]
  pipeline.py -h | --help

Options:
  -h --help             Show this screen.
  --image <filename>    Filename of seismogram.
  --output <directory>  Save metadata in <directory>.
  --stats <filename>    Write statistics (e.g. number of meanlines, size of ROI) to <filename>.
                        If <filename> already exists, stats will be appended, not overwritten.
  --scale <scale>       1 for a full-size seismogram, 0.25 for quarter-size, etc. [default: 1]
  --debug <directory>   Save intermediate steps as images for inspection in <directory>.
  --fix-seed            Fix random seed.

"""

from docopt import docopt

def analyze_image(in_file, out_dir, stats_file=False, scale=1, debug_dir=False, fix_seed=False):
  from lib.dir import ensure_dir_exists
  from lib.debug import Debug
  from lib.stats_recorder import Record

  if debug_dir:
    Debug.set_directory(debug_dir)

  if fix_seed:
    Debug.set_seed(1234567890)

  ensure_dir_exists(out_dir)

  from lib.timer import timeStart, timeEnd

  from lib.load_image import get_grayscale_image, image_as_float
  from lib.roi_detection import get_roi, corners_to_geojson
  from lib.polygon_mask import mask_image
  from lib.meanline_detection import detect_meanlines, meanlines_to_geojson
  from lib.geojson_io import save_features

  paths = {
    "roi": out_dir+"/roi.json",
    "meanlines": out_dir+"/meanlines.json",
    "intersections": out_dir+"/intersections.json",
    "segments": out_dir+"/segments.json",
    "segment_assignments": out_dir+"/segment_assignments.json"
  }

  timeStart("get roi and meanlines")

  timeStart("read image")
  img_gray = image_as_float(get_grayscale_image(in_file))
  timeEnd("read image")

  print "\n--ROI--"
  timeStart("get region of interest")
  corners = get_roi(img_gray, scale=scale)
  timeEnd("get region of interest")

  timeStart("convert roi to geojson")
  corners_as_geojson = corners_to_geojson(corners)
  timeEnd("convert roi to geojson")

  timeStart("saving roi as geojson")
  save_features(corners_as_geojson, paths["roi"])
  timeEnd("saving roi as geojson")


  print "\n--MASK IMAGE--"
  roi_polygon = corners_as_geojson["geometry"]["coordinates"][0]

  timeStart("mask image")
  masked_image = mask_image(img_gray, roi_polygon)
  timeEnd("mask image")

  Debug.save_image("main", "masked_image", masked_image.filled(0))


  print "\n--MEANLINES--"
  meanlines, meanline_stats = detect_meanlines(masked_image, corners, scale=scale, return_stats=True)

  timeStart("convert meanlines to geojson")
  meanlines_as_geojson = meanlines_to_geojson(meanlines)
  timeEnd("convert meanlines to geojson")

  timeStart("saving meanlines as geojson")
  save_features(meanlines_as_geojson, paths["meanlines"])
  timeEnd("saving meanlines as geojson")

  timeEnd("get roi and meanlines")

  if (stats_file):
    import json
    from lib.utilities import poly_area2D
    from lib.quality_control import points_to_rho_theta

    num_meanlines = len(meanlines)
    corners_clockwise = [
      corners["top_left"], corners["top_right"],
      corners["bottom_right"], corners["bottom_left"]
    ]
    roi_area = poly_area2D(corners_clockwise)
    _, roi_angle_top = points_to_rho_theta(corners["top_left"], corners["top_right"])
    _, roi_angle_bottom = points_to_rho_theta(corners["bottom_right"], corners["bottom_left"])
    theta_mode = meanline_stats["max_theta"]

    Record.record("num_meanlines", num_meanlines)
    Record.record("roi_area", roi_area)
    Record.record("roi_angle_top", roi_angle_top)
    Record.record("roi_angle_bottom", roi_angle_bottom)
    Record.record("theta_mode", theta_mode)
    
    Record.export_as_json(stats_file)

if __name__ == '__main__':
  arguments = docopt(__doc__)
  in_file = arguments["--image"]
  out_dir = arguments["--output"]
  stats_file = arguments["--stats"]
  scale = float(arguments["--scale"])
  debug_dir = arguments["--debug"]
  fix_seed = arguments["--fix-seed"]

  if (in_file and out_dir):
    segments = analyze_image(in_file, out_dir, stats_file, scale, debug_dir, fix_seed)
  else:
    print(arguments)
