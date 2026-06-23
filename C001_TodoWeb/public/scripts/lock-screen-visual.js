;(() => {
  const hm = document.getElementById('clock-hm')
  const sec = document.getElementById('clock-sec')
  const date = document.getElementById('date-display')

  if (!(hm instanceof HTMLElement) || !(sec instanceof HTMLElement) || !(date instanceof HTMLElement)) {
    return
  }

  const weekdays = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

  const updateClock = () => {
    const now = new Date()
    const hours = String(now.getHours()).padStart(2, '0')
    const minutes = String(now.getMinutes()).padStart(2, '0')
    const seconds = String(now.getSeconds()).padStart(2, '0')
    const year = now.getFullYear()
    const month = String(now.getMonth() + 1).padStart(2, '0')
    const day = String(now.getDate()).padStart(2, '0')

    hm.textContent = `${hours}:${minutes}`
    sec.textContent = seconds
    date.textContent = `${year}-${month}-${day} ${weekdays[now.getDay()]} / System online`
  }

  window.setInterval(updateClock, 1000)
  updateClock()
})()

;(() => {
  if (!('THREE' in window)) {
    return
  }

  const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
  if (motionQuery.matches) {
    return
  }

  const connection = navigator.connection || navigator.mozConnection || navigator.webkitConnection
  const lowPowerMode =
    (typeof navigator.hardwareConcurrency === 'number' && navigator.hardwareConcurrency <= 4) ||
    (typeof navigator.deviceMemory === 'number' && navigator.deviceMemory <= 4) ||
    (connection && connection.saveData)

  const interactiveMotion = !lowPowerMode && window.matchMedia('(pointer:fine)').matches

  const container = document.getElementById('webgl-container')
  if (!(container instanceof HTMLElement)) {
    return
  }

  const THREE = window.THREE
  const scene = new THREE.Scene()
  scene.fog = new THREE.FogExp2(0x000000, 0.002)

  const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000)
  camera.position.z = 150

  const renderer = new THREE.WebGLRenderer({
    alpha: true,
    antialias: !lowPowerMode,
    powerPreference: lowPowerMode ? 'low-power' : 'high-performance'
  })
  renderer.setSize(window.innerWidth, window.innerHeight)
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, lowPowerMode ? 1 : 1.5))
  container.appendChild(renderer.domElement)

  const particleCount = lowPowerMode ? 12000 : 25000
  const geometry = new THREE.BufferGeometry()
  const positions = new Float32Array(particleCount * 3)
  const sizes = new Float32Array(particleCount)
  const phases = new Float32Array(particleCount)

  for (let i = 0; i < particleCount; i++) {
    const phi = Math.acos(-1 + (2 * i) / particleCount)
    const theta = Math.sqrt(particleCount * Math.PI) * phi

    let radius = 80
    radius += Math.sin(theta * 3) * Math.cos(phi * 5) * 20

    positions[i * 3] = radius * Math.cos(theta) * Math.sin(phi)
    positions[i * 3 + 1] = radius * Math.sin(theta) * Math.sin(phi)
    positions[i * 3 + 2] = radius * Math.cos(phi)

    sizes[i] = Math.random() * 1.5 + 0.5
    phases[i] = Math.random() * Math.PI * 2
  }

  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  geometry.setAttribute('size', new THREE.BufferAttribute(sizes, 1))
  geometry.setAttribute('phase', new THREE.BufferAttribute(phases, 1))

  const vertexShader = `
    attribute float size;
    attribute float phase;
    varying float vOpacity;
    uniform float time;
    uniform float targetScale;
    uniform float wobbleAmp;
    
    void main() {
      vOpacity = 0.4 + 0.6 * sin(phase + time * 2.0);
      
      vec3 pos = position;
      pos += normalize(position) * (sin(time + phase) * wobbleAmp);
      
      vec4 mvPosition = modelViewMatrix * vec4(pos, 1.0);
      gl_PointSize = size * targetScale * (100.0 / -mvPosition.z);
      gl_Position = projectionMatrix * mvPosition;
    }
  `

  const fragmentShader = `
    varying float vOpacity;
    void main() {
      vec2 xy = gl_PointCoord.xy - vec2(0.5);
      float ll = length(xy);
      if (ll > 0.5) discard;
      
      float intensity = 1.0 - (ll * 2.0);
      vec3 color = vec3(0.9, 0.95, 1.0);
      gl_FragColor = vec4(color, vOpacity * intensity * 0.8);
    }
  `

  const material = new THREE.ShaderMaterial({
    uniforms: {
      time: { value: 0 },
      targetScale: { value: 1.0 },
      wobbleAmp: { value: lowPowerMode ? 0.35 : 0.6 }
    },
    vertexShader,
    fragmentShader,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending
  })

  const particles = new THREE.Points(geometry, material)
  scene.add(particles)

  let mouseX = 0
  let mouseY = 0
  let windowHalfX = window.innerWidth / 2
  let windowHalfY = window.innerHeight / 2

  const onPointerMove = (event) => {
    mouseX = event.clientX - windowHalfX
    mouseY = event.clientY - windowHalfY
  }

  if (interactiveMotion) {
    window.addEventListener('pointermove', onPointerMove, { passive: true })
  }

  let baseRotationSpeed = lowPowerMode ? 0.00035 : 0.0005
  let rotationSpeed = baseRotationSpeed
  let targetRotationSpeed = baseRotationSpeed
  let particleScale = 1.0
  let targetParticleScale = 1.0
  const clock = new THREE.Clock()

  camera.lookAt(scene.position)

  const bumpEffect = () => {
    targetRotationSpeed = baseRotationSpeed * 10
    targetParticleScale = 2.0

    window.setTimeout(() => {
      targetRotationSpeed = baseRotationSpeed
      targetParticleScale = 1.0
    }, 3000)
  }

  window.addEventListener('aegis:unlock', bumpEffect)
  window.addEventListener('aegis:reveal-ui', bumpEffect)

  let rafId = 0
  let running = true

  const render = () => {
    if (!running) {
      return
    }

    rafId = window.requestAnimationFrame(render)

    const time = clock.getElapsedTime()

    rotationSpeed += (targetRotationSpeed - rotationSpeed) * 0.05
    particleScale += (targetParticleScale - particleScale) * 0.05

    material.uniforms.time.value = time
    material.uniforms.targetScale.value = particleScale

    particles.rotation.y += rotationSpeed
    particles.rotation.x += rotationSpeed * 0.5

    if (interactiveMotion) {
      camera.position.x += (mouseX * 0.05 - camera.position.x) * 0.02
      camera.position.y += (-mouseY * 0.05 - camera.position.y) * 0.02
      camera.lookAt(scene.position)
    }

    renderer.render(scene, camera)
  }

  const stop = () => {
    running = false
    window.cancelAnimationFrame(rafId)
  }

  const start = () => {
    if (running) {
      return
    }

    running = true
    clock.getDelta()
    rafId = window.requestAnimationFrame(render)
  }

  document.addEventListener(
    'visibilitychange',
    () => {
      if (document.hidden) {
        stop()
      } else {
        start()
      }
    },
    { passive: true }
  )

  render()

  window.addEventListener(
    'resize',
    () => {
      windowHalfX = window.innerWidth / 2
      windowHalfY = window.innerHeight / 2
      camera.aspect = window.innerWidth / window.innerHeight
      camera.updateProjectionMatrix()
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, lowPowerMode ? 1 : 1.5))
      renderer.setSize(window.innerWidth, window.innerHeight)
    },
    { passive: true }
  )
})()
