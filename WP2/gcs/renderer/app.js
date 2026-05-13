'use strict'

// ── Config — edit these to match your setup ───────────────────────────────────
const WS_URL        = 'ws://localhost:9090'          // rosbridge WebSocket
const VIDEO_BASE    = 'http://localhost:8080/stream?topic=' // web_video_server
const RECONNECT_MS  = 3000

// ── Topic names ───────────────────────────────────────────────────────────────
const T_POSE    = '/drone/pose'
const T_TARGET  = '/cerebro/target'
const T_VEL     = '/drone/cmd_vel'
// Stub topics — uncomment when live:
// const T_CAM_FRONT = '/sensor/camera_front'
// const T_CAM_DOWN  = '/sensor/camera_down'
// const T_ODOM      = '/slam/odom'
// const T_BATTERY   = '/sensor/battery'

// ── Colours ───────────────────────────────────────────────────────────────────
const C = {
  bg:     '#1a1d23',
  panel:  '#252830',
  border: '#333740',
  accent: '#4fc3f7',
  green:  '#4caf50',
  red:    '#e53935',
  orange: '#ff9800',
  text:   '#e0e0e0',
  dim:    '#616161',
  trail:  '#546e7a',
}

const TEST_BARS = [
  '#c0c0c0', '#c0c000', '#00c0c0', '#00c000',
  '#c000c0', '#c00000', '#0000c0', '#181818',
]

// ── Helpers ───────────────────────────────────────────────────────────────────

function bindCanvas (canvas) {
  const ro = new ResizeObserver(() => {
    canvas.width  = canvas.offsetWidth
    canvas.height = canvas.offsetHeight
    canvas._onresize && canvas._onresize()
  })
  ro.observe(canvas)
}

// ── VideoPanel ─────────────────────────────────────────────────────────────────

class VideoPanel {
  constructor (canvasEl, label) {
    this.canvas = canvasEl
    this.ctx    = canvasEl.getContext('2d')
    this.label  = label
    this._mjpegImg = null
    this._rafId    = null

    bindCanvas(canvasEl)
    canvasEl._onresize = () => this._draw()
    this._draw()
  }

  _draw () {
    const { canvas, ctx } = this
    const w = canvas.width, h = canvas.height
    if (!w || !h) return

    if (this._mjpegImg && this._mjpegImg.complete && this._mjpegImg.naturalWidth) {
      ctx.drawImage(this._mjpegImg, 0, 0, w, h)
      return
    }

    // SMPTE colour-bar test pattern
    const barW = w / TEST_BARS.length
    const barH = Math.floor(h * 0.62)
    TEST_BARS.forEach((clr, i) => {
      ctx.fillStyle = clr
      ctx.fillRect(Math.floor(i * barW), 0, Math.ceil(barW), barH)
    })
    ctx.fillStyle = '#0a0a0a'
    ctx.fillRect(0, barH, w, h - barH)

    ctx.textAlign = 'center'
    ctx.font      = 'bold 13px Monospace'
    ctx.fillStyle = '#ffffff'
    ctx.fillText('NO  SIGNAL', w / 2, h / 2 + 14)

    ctx.font      = '8px Monospace'
    ctx.fillStyle = C.accent
    ctx.fillText(`[ ${this.label} ]`, w / 2, h / 2 + 30)

    ctx.textAlign = 'left'
    ctx.font      = '7px Monospace'
    ctx.fillStyle = C.dim
    ctx.fillText(this.label, 6, 14)
  }

  // Connect to a MJPEG stream from web_video_server.
  // Call this once when ros-jazzy-web-video-server is running on the Pi.
  connectMJPEG (topicName) {
    const url = `${VIDEO_BASE}${topicName}`
    const img = new Image()
    img.onload = () => { this._mjpegImg = img; this._startLoop() }
    img.onerror = () => { this._mjpegImg = null }
    img.src = url
  }

  _startLoop () {
    const tick = () => { this._draw(); this._rafId = requestAnimationFrame(tick) }
    if (this._rafId) cancelAnimationFrame(this._rafId)
    this._rafId = requestAnimationFrame(tick)
  }

  // For future sensor_msgs/Image callbacks decoded server-side:
  updateFrame (imageBitmap) {
    this._mjpegImg = imageBitmap
    this._draw()
  }
}

// ── NavMapPanel ────────────────────────────────────────────────────────────────

class NavMapPanel {
  constructor (canvasEl) {
    this.canvas = canvasEl
    this.ctx    = canvasEl.getContext('2d')
    this.x      = 0
    this.y      = 0
    this.yaw    = 0
    this.trail  = []
    this.TRAIL_MAX = 300
    this.SCALE     = 28  // pixels per metre

    bindCanvas(canvasEl)
    canvasEl._onresize = () => this._draw()
    this._draw()
  }

  _toPx (x, y) {
    const cx = this.canvas.width  / 2
    const cy = this.canvas.height / 2
    return [cx + x * this.SCALE, cy - y * this.SCALE]
  }

  _draw () {
    const { canvas, ctx } = this
    const w = canvas.width, h = canvas.height
    if (!w || !h) return

    ctx.fillStyle = C.bg
    ctx.fillRect(0, 0, w, h)

    // Grid
    const cx = w / 2, cy = h / 2, s = this.SCALE
    ctx.lineWidth = 1
    for (let dx = -Math.ceil(w / s); dx <= Math.ceil(w / s); dx++) {
      const gx = cx + dx * s
      ctx.strokeStyle = dx === 0 ? C.dim : C.border
      ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, h); ctx.stroke()
    }
    for (let dy = -Math.ceil(h / s); dy <= Math.ceil(h / s); dy++) {
      const gy = cy + dy * s
      ctx.strokeStyle = dy === 0 ? C.dim : C.border
      ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(w, gy); ctx.stroke()
    }

    // North label
    ctx.font = 'bold 9px Monospace'; ctx.fillStyle = C.accent; ctx.textAlign = 'left'
    ctx.fillText('N ↑', cx + 4, 16)

    // Trail
    if (this.trail.length >= 2) {
      ctx.strokeStyle = C.trail; ctx.lineWidth = 1
      ctx.beginPath()
      this.trail.forEach(([tx, ty], i) => {
        const [px, py] = this._toPx(tx, ty)
        i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py)
      })
      ctx.stroke()
    }

    // Drone dot
    const [px, py] = this._toPx(this.x, this.y)
    ctx.beginPath(); ctx.arc(px, py, 7, 0, Math.PI * 2)
    ctx.fillStyle = C.green; ctx.fill()
    ctx.strokeStyle = '#fff'; ctx.lineWidth = 1; ctx.stroke()

    // Heading arrow
    const ax = px + 15 * Math.cos(this.yaw - Math.PI / 2)
    const ay = py + 15 * Math.sin(this.yaw - Math.PI / 2)
    ctx.strokeStyle = C.green; ctx.lineWidth = 2
    ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(ax, ay); ctx.stroke()

    const ang = Math.atan2(ay - py, ax - px)
    ctx.fillStyle = C.green; ctx.beginPath()
    ctx.moveTo(ax, ay)
    ctx.lineTo(ax - 8 * Math.cos(ang - 0.4), ay - 8 * Math.sin(ang - 0.4))
    ctx.lineTo(ax - 8 * Math.cos(ang + 0.4), ay - 8 * Math.sin(ang + 0.4))
    ctx.closePath(); ctx.fill()

    // Pending note
    ctx.font = '7px Monospace'; ctx.fillStyle = C.dim; ctx.textAlign = 'left'
    ctx.fillText('nav_msgs/Odometry  (pending — using /drone/pose)', 6, h - 6)
  }

  // Called from ROS /drone/pose callback (and future /slam/odom)
  updatePose (x, y, yaw) {
    this.x = x; this.y = y; this.yaw = yaw
    this.trail.push([x, y])
    if (this.trail.length > this.TRAIL_MAX) this.trail.shift()
    this._draw()
  }
}

// ── SpeedGauge ─────────────────────────────────────────────────────────────────

class SpeedGauge {
  constructor (canvasEl) {
    this.canvas = canvasEl
    this.ctx    = canvasEl.getContext('2d')
    this.value  = 0
    this.MAX    = 10

    bindCanvas(canvasEl)
    canvasEl._onresize = () => this._draw()
    this._draw()
  }

  _draw () {
    const { canvas, ctx } = this
    const w = canvas.width, h = canvas.height
    if (!w || !h) return

    ctx.fillStyle = C.panel; ctx.fillRect(0, 0, w, h)

    const cx   = w / 2
    const cy   = h * 0.58
    const r    = Math.min(cx - 14, cy - 8) * 0.88
    const frac = Math.min(this.value / this.MAX, 1)

    // Background arc
    ctx.beginPath(); ctx.arc(cx, cy, r, Math.PI, 0, false)
    ctx.strokeStyle = C.border; ctx.lineWidth = 9; ctx.stroke()

    // Value arc
    if (frac > 0.005) {
      const clr = frac < 0.6 ? C.green : frac < 0.85 ? C.orange : C.red
      ctx.beginPath(); ctx.arc(cx, cy, r, Math.PI, Math.PI * (1 + frac), false)
      ctx.strokeStyle = clr; ctx.lineWidth = 9; ctx.stroke()
    }

    // Needle
    const angle = Math.PI * (1 + frac)
    const nx = cx + r * 0.78 * Math.cos(angle)
    const ny = cy + r * 0.78 * Math.sin(angle)
    ctx.strokeStyle = '#fff'; ctx.lineWidth = 2
    ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(nx, ny); ctx.stroke()
    ctx.beginPath(); ctx.arc(cx, cy, 4, 0, Math.PI * 2)
    ctx.fillStyle = C.panel; ctx.fill()
    ctx.strokeStyle = '#aaa'; ctx.lineWidth = 1; ctx.stroke()

    // Readout
    ctx.textAlign = 'center'
    ctx.font = 'bold 14px Monospace'; ctx.fillStyle = '#fff'
    ctx.fillText(this.value.toFixed(1), cx, cy + 16)
    ctx.font = '8px Monospace'; ctx.fillStyle = C.dim
    ctx.fillText('m/s  SPEED', cx, cy + 30)

    // Scale end-labels
    ctx.font = '7px Monospace'; ctx.fillStyle = C.dim
    ctx.textAlign = 'right'; ctx.fillText('0', cx - r - 2, cy + 5)
    ctx.textAlign = 'left';  ctx.fillText(String(this.MAX), cx + r + 2, cy + 5)
  }

  setValue (v) { this.value = Math.max(0, v); this._draw() }
}

// ── AltitudeBar ────────────────────────────────────────────────────────────────

class AltitudeBar {
  constructor (fillEl, labelEl) {
    this.fill  = fillEl
    this.label = labelEl
    this.MAX   = 10
  }

  setValue (v) {
    const frac = Math.min(Math.max(v, 0) / this.MAX, 1)
    this.fill.style.height     = `${frac * 100}%`
    this.fill.style.background = frac < 0.8 ? C.accent : C.red
    this.label.textContent     = `${v.toFixed(1)} m`
  }
}

// ── BatteryBar ─────────────────────────────────────────────────────────────────

class BatteryBar {
  constructor (fillEl, labelEl) {
    this.fill  = fillEl
    this.label = labelEl
  }

  setValue (pct) {
    pct = Math.min(Math.max(pct, 0), 100)
    const clr    = pct > 30 ? C.green : pct > 15 ? C.orange : C.red
    const blocks = Math.round(pct / 10)
    this.fill.style.width      = `${pct}%`
    this.fill.style.background = clr
    this.label.style.color     = clr
    this.label.textContent     = `${Math.round(pct)} %  ${'█'.repeat(blocks)}${'░'.repeat(10 - blocks)}`
  }
}

// ── BarcodeLog ─────────────────────────────────────────────────────────────────

class BarcodeLog {
  constructor (tbodyEl, placeholderEl, scrollEl) {
    this.tbody       = tbodyEl
    this.placeholder = placeholderEl
    this.scroll      = scrollEl
  }

  // Wire to the future barcode detection callback
  addEntry (timestamp, barcode, shelf, row, confidence) {
    this.placeholder.style.display = 'none'
    const tr = document.createElement('tr')
    for (const val of [timestamp, barcode, shelf, row, confidence]) {
      const td = document.createElement('td')
      td.textContent = val
      tr.appendChild(td)
    }
    this.tbody.appendChild(tr)
    this.scroll.scrollTop = this.scroll.scrollHeight
  }
}

// ── GCS App ───────────────────────────────────────────────────────────────────

class GCSApp {
  constructor () {
    this._ros     = null
    this._subs    = []
    this._widgets = this._buildWidgets()
    this._connect()
  }

  _buildWidgets () {
    return {
      cam1:  new VideoPanel(document.getElementById('cam1-canvas'), 'CAM FRONT'),
      cam2:  new VideoPanel(document.getElementById('cam2-canvas'), 'CAM DOWN'),
      nav:   new NavMapPanel(document.getElementById('nav-canvas')),
      speed: new SpeedGauge(document.getElementById('speed-canvas')),
      alt:   new AltitudeBar(
        document.getElementById('alt-fill'),
        document.getElementById('alt-label'),
      ),
      bat: new BatteryBar(
        document.getElementById('bat-fill'),
        document.getElementById('bat-label'),
      ),
      log: new BarcodeLog(
        document.getElementById('log-tbody'),
        document.getElementById('log-placeholder'),
        document.getElementById('log-scroll'),
      ),
    }
  }

  _setStatus (text, colour) {
    const el = document.getElementById('status')
    el.textContent = text
    el.style.color = colour
  }

  // ── ROS connection ──────────────────────────────────────────────────────────

  _connect () {
    this._setStatus('● CONNECTING…', C.orange)

    this._ros = new ROSLIB.Ros({ url: WS_URL })  // eslint-disable-line no-undef

    this._ros.on('connection', () => {
      this._setStatus('● ONLINE', C.green)
      this._subscribe()
    })

    this._ros.on('error', (err) => {
      console.error('[GCS] rosbridge error', err)
      this._setStatus('● ERROR', C.red)
    })

    this._ros.on('close', () => {
      this._setStatus('● OFFLINE — reconnecting…', C.red)
      this._subs = []
      setTimeout(() => this._connect(), RECONNECT_MS)
    })
  }

  // ── Topic subscriptions ─────────────────────────────────────────────────────

  _sub (name, type, cb) {
    const topic = new ROSLIB.Topic({ ros: this._ros, name, messageType: type })  // eslint-disable-line no-undef
    topic.subscribe(cb)
    this._subs.push(topic)
    return topic
  }

  _subscribe () {
    const w = this._widgets

    // /drone/pose → nav map, altitude, header pose display
    this._sub(T_POSE, 'std_msgs/Float32MultiArray', (msg) => {
      const [x, y, z, yaw = 0] = msg.data
      w.nav.updatePose(x, y, yaw)
      w.alt.setValue(z)
      document.getElementById('pose-display').textContent =
        `Pose  X:${x.toFixed(2)}  Y:${y.toFixed(2)}  Z:${z.toFixed(2)}` +
        `  Yaw:${(yaw * 180 / Math.PI).toFixed(1)}°`
    })

    // /drone/cmd_vel → speed gauge (magnitude of linear velocity)
    this._sub(T_VEL, 'geometry_msgs/Twist', (msg) => {
      const { x, y, z } = msg.linear
      w.speed.setValue(Math.sqrt(x * x + y * y + z * z))
    })

    // ── Stub subscriptions — uncomment one by one as topics go live ───────────

    // /slam/odom → nav map (replaces /drone/pose for the map)
    // this._sub(T_ODOM, 'nav_msgs/Odometry', (msg) => {
    //   const p   = msg.pose.pose.position
    //   const q   = msg.pose.pose.orientation
    //   const yaw = Math.atan2(2*(q.w*q.z + q.x*q.y), 1 - 2*(q.y*q.y + q.z*q.z))
    //   w.nav.updatePose(p.x, p.y, yaw)
    // })

    // /sensor/battery → battery bar
    // this._sub(T_BATTERY, 'std_msgs/Float32', (msg) => {
    //   w.bat.setValue(msg.data)
    // })

    // Camera MJPEG streams (requires ros-jazzy-web-video-server on the Pi)
    // w.cam1.connectMJPEG(T_CAM_FRONT)
    // w.cam2.connectMJPEG(T_CAM_DOWN)
  }
}

// ── Boot ──────────────────────────────────────────────────────────────────────

window.addEventListener('DOMContentLoaded', () => {
  window._gcs = new GCSApp()
})
