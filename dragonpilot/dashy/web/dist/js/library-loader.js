
// Dynamic Library Loader
window.loadLibrary = function(name) {
  if (name === 'hls') {
    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = '/lib/' + name + '.min.js';
      script.onload = resolve;
      script.onerror = reject;
      document.head.appendChild(script);
    });
  }
};

window.loadHls = function() { return window.loadLibrary('hls'); };
