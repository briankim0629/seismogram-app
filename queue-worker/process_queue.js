var Queue = require('firebase-queue'),
    Firebase = require("firebase"),
    mkdirp = require("mkdirp"),
    rimraf = require("rimraf"),
    async = require("async"),
    exec = require("child_process").exec,
    fs = require("fs");

// post machine presence to firebase
require("./presence");

var rootRef = require("./rootRef");
var status = require("./status");
var logPath = __dirname + "/logs";

var queueRef = rootRef.child("queue");
var opts = { specId: "seismoSpec" };
var queue = new Queue(queueRef, opts, function(data, progress, resolve, reject) {
  console.log("received new job:");
  console.log(data);

  var filename = data.filename;
  processSeismo(filename, function(err) {
    if (err) {
      console.log("failed to process "+filename+"; marking job rejected");
      setStatus(filename, status.failed);
      reject(err);
      return;
    }
    console.log("successfully processed "+filename+"; marking job resolved");
    resolve();
  });
});

var processSeismo = function(filename, callback) {  
  var command = "sh process_task.sh " + filename;

  console.log(command);
  // if (process.env.NODE_ENV !== "production") {
  //   command += " dev";
  // }

  new_process = exec(command, function(err, stdout, stderr) {
    var log = "== stdout ==\n";
    log += stdout;
    log += "\n== stderr ==\n";
    log += stderr;
    console.log(log);

    var seismoLogDir = logPath + "/" + filename;

    async.series([
      function(cb) { writeLog(seismoLogDir, log, cb); },
      function(cb) { uploadLog(filename, seismoLogDir, cb); },
      function(cb) { rimraf(seismoLogDir, cb); }
    ]);

    if (err) {
      // not totally sure what kind of error this would be
      callback(err);
      return;
    }

    var pipelineFailure = checkFailure(stderr);
    callback(pipelineFailure);
  });

  // If we wanted progress callbacks, we could scrape
  // these data events for meaningful tidbits, like
  // the headers that get print out whenever we switch
  // sections.
  // 
  // new_process.stdout.on("data", function(data) {
  //   console.log("stdout: " + data);
  // });
}

var checkFailure = function(stderr) {
  // TODO: More robust test for python script error
  if (/Traceback/.test(stderr)) {
    return true;
  }
  return;
}

var writeLog = function(logDir, logContents, callback) {
  if (!fs.existsSync(logDir)) {
    mkdirp.sync(logDir);
  }

  var path = logDir + "/log.txt";

  fs.writeFile(path, logContents, function(err) {
    if (err) {
      console.log("error writing to log", filename, err);
      return;
    }
    if (typeof callback === "function") callback();
  });
};

var uploadLog = function(filename, logDir, callback) {
  var command = "sh copy_to_s3.sh " + filename + " " + logDir + " logs";
  console.log(command);
  exec(command, function(err) {
    if (err) {
      console.log("error copying log to s3", err);
    }
    if (typeof callback === "function") callback();
  });
}

var setStatus = function(filename, status) {
  var command = "sh set_seismo_status.sh " + filename + " " + status;
  console.log(command);
  exec(command, function(err) {
    if (err) {
      console.log("error setting seismo status", err);
      return;
    }
  });
}

process.on('SIGINT', function() {
  console.log('Starting queue shutdown');
  queue.shutdown().then(function() {
    console.log('Finished queue shutdown');
    process.exit(0);
  });
});
