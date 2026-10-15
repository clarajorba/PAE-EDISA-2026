'use strict'
// Preload runs in a privileged context between main and renderer.
// Nothing needs to be bridged for now — roslib communicates over WebSocket
// entirely from the renderer, no Node APIs required.
