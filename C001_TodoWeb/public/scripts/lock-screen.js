;(() => {
  const form = document.getElementById('lock-screen-form')
  const passwordInput = document.getElementById('lock-password')
  const status = document.getElementById('lock-screen-status')
  const clockContainer = document.getElementById('lock-screen-clock')
  const particleTrigger = document.getElementById('webgl-container') ?? form?.closest('.aegis-lockscreen')

  const unlockBtn = document.getElementById('unlock-btn')
  const progressCircle = document.getElementById('progress-circle')
  const unlockText = document.getElementById('unlock-text')
  const cancelButton = document.getElementById('lock-screen-cancel')

  if (
    !(form instanceof HTMLFormElement) ||
    !(passwordInput instanceof HTMLInputElement) ||
    !(status instanceof HTMLElement)
  ) {
    return
  }

  const submitButton = form.querySelector('button[type="submit"]')
  if (!(submitButton instanceof HTMLButtonElement)) {
    return
  }

  const defaultStatus = status.textContent?.trim() || ''
  const redirectTarget = form.dataset.redirect || '/'

  const circumference = 270
  const totalHoldTime = 1500
  const revealTapCount = 5
  const revealTapGapMs = 1200

  let busy = false
  let holding = false
  let holdStartAt = 0
  let holdRafId = 0
  let revealTapStreak = 0
  let lastRevealTapAt = 0
  let uiRevealed = form.dataset.revealed === 'true'

  const defaultUnlockText =
    unlockText instanceof HTMLElement ? unlockText.textContent?.trim() || 'Hold to verify' : 'Hold to verify'

  const updateStatus = (message, state = 'idle') => {
    status.textContent = message
    status.dataset.state = state
    form.dataset.state = state
  }

  const setBusy = (nextBusy) => {
    busy = Boolean(nextBusy)
    passwordInput.disabled = busy
    submitButton.disabled = busy
    submitButton.setAttribute('aria-busy', String(busy))

    if (cancelButton instanceof HTMLButtonElement) {
      cancelButton.disabled = busy
    }

    if (unlockBtn instanceof HTMLElement) {
      unlockBtn.setAttribute('aria-disabled', String(busy))
    }
  }

  const setUnlockLabel = (text, { blinking } = { blinking: false }) => {
    if (!(unlockText instanceof HTMLElement)) {
      return
    }

    unlockText.textContent = text
    unlockText.classList.toggle('blink-cursor', Boolean(blinking))
  }

  const setUiRevealed = (revealed) => {
    uiRevealed = Boolean(revealed)
    form.dataset.revealed = uiRevealed ? 'true' : 'false'
    form.setAttribute('aria-hidden', String(!uiRevealed))

    if (clockContainer instanceof HTMLElement) {
      clockContainer.dataset.revealed = uiRevealed ? 'true' : 'false'
      clockContainer.setAttribute('aria-hidden', String(!uiRevealed))
    }

    if (uiRevealed) {
      form.removeAttribute('inert')
      passwordInput.removeAttribute('tabindex')

      if (unlockBtn instanceof HTMLElement) {
        unlockBtn.tabIndex = 0
      }

      if (cancelButton instanceof HTMLButtonElement) {
        cancelButton.removeAttribute('tabindex')
      }

      updateStatus(defaultStatus)
      setUnlockLabel(defaultUnlockText, { blinking: !busy })
      window.setTimeout(() => passwordInput.focus(), 120)
      window.dispatchEvent(new CustomEvent('aegis:reveal-ui'))
      return
    }

    form.setAttribute('inert', '')
    passwordInput.tabIndex = -1
    submitButton.tabIndex = -1

    if (unlockBtn instanceof HTMLElement) {
      unlockBtn.tabIndex = -1
    }

    if (cancelButton instanceof HTMLButtonElement) {
      cancelButton.tabIndex = -1
    }
  }

  const setProgress = (elapsedMs) => {
    if (!(progressCircle instanceof SVGElement)) {
      return
    }

    const ratio = Math.max(0, Math.min(1, elapsedMs / totalHoldTime))
    const offset = circumference - ratio * circumference
    progressCircle.style.strokeDashoffset = String(offset)
  }

  const normalizeErrorMessage = (message) => {
    switch (message) {
      case 'Password is required.':
        return 'Please enter the access password.'
      case 'Password is incorrect.':
        return 'The access password is incorrect.'
      case 'Invalid request payload.':
        return 'The request format is invalid.'
      case 'Could not create lock screen session.':
        return 'Could not create the lock screen session.'
      case 'Lock screen password is not configured.':
        return 'The lock screen password is not configured.'
      default:
        return message
    }
  }

  const authorize = async () => {
    if (busy) {
      return
    }

    const password = passwordInput.value.trim()

    if (!password) {
      updateStatus('Please enter the access password.', 'error')
      setUnlockLabel('Password required', { blinking: false })
      passwordInput.focus()
      return
    }

    setBusy(true)
    updateStatus('Verifying...', 'pending')
    setUnlockLabel('Verifying...', { blinking: false })

    try {
      const response = await fetch('/api/lock/session', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ password })
      })

      const result = await response.json().catch(() => null)
      const errorMessage =
        result &&
        typeof result === 'object' &&
        'error' in result &&
        typeof result.error === 'string'
          ? normalizeErrorMessage(result.error)
          : 'Verification failed.'

      if (!response.ok) {
        throw new Error(errorMessage)
      }

      updateStatus('Verified. Entering...', 'success')
      setUnlockLabel('Verified', { blinking: false })

      if (unlockBtn instanceof HTMLElement) {
        unlockBtn.classList.add('active')
      }

      window.dispatchEvent(new CustomEvent('aegis:unlock'))
      window.setTimeout(() => {
        window.location.assign(redirectTarget)
      }, 320)
    } catch (error) {
      updateStatus(error instanceof Error ? normalizeErrorMessage(error.message) : 'Verification failed.', 'error')
      setUnlockLabel('Failed', { blinking: false })

      passwordInput.focus()
      passwordInput.select()
      setBusy(false)

      holding = false
      window.cancelAnimationFrame(holdRafId)
      holdRafId = 0
      setProgress(0)

      if (unlockBtn instanceof HTMLElement) {
        unlockBtn.classList.remove('active')
      }

      window.setTimeout(() => {
        if (!busy) {
          setUnlockLabel(defaultUnlockText, { blinking: true })
        }
      }, 1400)
    }
  }

  passwordInput.addEventListener('input', () => {
    updateStatus(defaultStatus)
    if (!busy) {
      setUnlockLabel(defaultUnlockText, { blinking: true })
    }
  })

  form.addEventListener('submit', (event) => {
    event.preventDefault()
    void authorize()
  })

  setUiRevealed(uiRevealed)

  if (particleTrigger instanceof HTMLElement) {
    particleTrigger.addEventListener(
      'click',
      () => {
        if (uiRevealed) {
          return
        }

        const now = performance.now()
        revealTapStreak = now - lastRevealTapAt <= revealTapGapMs ? revealTapStreak + 1 : 1
        lastRevealTapAt = now

        if (revealTapStreak >= revealTapCount) {
          revealTapStreak = 0
          setUiRevealed(true)
        }
      },
      { passive: true }
    )
  }

  if (progressCircle instanceof SVGElement) {
    progressCircle.style.strokeDasharray = String(circumference)
    progressCircle.style.strokeDashoffset = String(circumference)
  }

  const holdTick = (now) => {
    if (!holding) {
      return
    }

    const elapsed = now - holdStartAt
    setProgress(elapsed)

    if (elapsed >= totalHoldTime) {
      holding = false
      setProgress(totalHoldTime)
      void authorize()
      return
    }

    holdRafId = window.requestAnimationFrame(holdTick)
  }

  const startHold = () => {
    if (busy || holding) {
      return
    }

    if (!passwordInput.value.trim()) {
      updateStatus('Please enter the access password.', 'error')
      setUnlockLabel('Password required', { blinking: false })
      passwordInput.focus()
      return
    }

    holding = true
    holdStartAt = performance.now()
    updateStatus('Hold to complete verification...', 'pending')
    setUnlockLabel('Verifying...', { blinking: false })

    holdRafId = window.requestAnimationFrame(holdTick)
  }

  const endHold = () => {
    if (!holding) {
      return
    }

    holding = false
    window.cancelAnimationFrame(holdRafId)
    holdRafId = 0
    setProgress(0)

    if (!busy) {
      updateStatus(defaultStatus)
      setUnlockLabel(defaultUnlockText, { blinking: true })
    }
  }

  const cancelUnlock = () => {
    if (busy || !uiRevealed) {
      return
    }

    endHold()
    passwordInput.value = ''
    passwordInput.blur()
    updateStatus(defaultStatus)
    setUnlockLabel(defaultUnlockText, { blinking: true })

    if (unlockBtn instanceof HTMLElement) {
      unlockBtn.classList.remove('active')
    }

    revealTapStreak = 0
    lastRevealTapAt = 0
    setUiRevealed(false)
  }

  if (unlockBtn instanceof HTMLElement) {
    unlockBtn.addEventListener(
      'pointerdown',
      (event) => {
        if (busy) {
          return
        }

        // Only react to the primary button for mouse pointers.
        if (event.pointerType === 'mouse' && event.button !== 0) {
          return
        }

        try {
          unlockBtn.setPointerCapture(event.pointerId)
        } catch {
          // Ignore browsers that don't support pointer capture here.
        }

        startHold()
      },
      { passive: true }
    )

    unlockBtn.addEventListener('pointerup', endHold, { passive: true })
    unlockBtn.addEventListener('pointercancel', endHold, { passive: true })
    unlockBtn.addEventListener('pointerleave', endHold, { passive: true })

    // Keyboard accessibility: Space behaves like a hold, Enter submits instantly.
    unlockBtn.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault()
        void authorize()
        return
      }

      if (event.key === ' ') {
        event.preventDefault()
        startHold()
      }
    })

    unlockBtn.addEventListener('keyup', (event) => {
      if (event.key === ' ') {
        event.preventDefault()
        endHold()
      }
    })
  }

  if (cancelButton instanceof HTMLButtonElement) {
    cancelButton.addEventListener('click', cancelUnlock)
  }

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') {
      return
    }

    if (!uiRevealed || busy) {
      return
    }

    event.preventDefault()
    cancelUnlock()
  })
})()
