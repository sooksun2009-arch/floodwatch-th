import { useEffect, useRef, useState } from 'react'
import { api, ApiError, levelLabel } from '../api'
import { useT } from '../i18n'

const SESSION_KEY = 'floodwatch_chat_session'

const sessionId = (() => {
  try {
    let id = sessionStorage.getItem(SESSION_KEY)
    if (!id) {
      id = Math.random().toString(36).slice(2) + Date.now().toString(36)
      sessionStorage.setItem(SESSION_KEY, id)
    }
    return id
  } catch {
    return null // storage blocked; the server treats it as an anonymous turn
  }
})()

// Built per render rather than held as a constant: it is translated, and the
// English version says outright that the answers come back in Thai. Claiming
// otherwise would be discovered on the first question.
const greeting = (t, lang) => ({
  role: 'bot',
  text: lang === 'en'
    ? `${t('chat.greeting')}

${t('chat.answersInThai')}`
    : t('chat.greeting'),
})

export default function ChatWidget({ open, setOpen, pendingMessage, onConsumed, onShowRoute, onOpenCamera }) {
  const { t, lang } = useT()
  const [messages, setMessages] = useState(() => [greeting(t, lang)])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [starters, setStarters] = useState([])

  // The label is translated; the message sent is not. The assistant matches
  // Thai patterns, so an English payload would give a chip that looks
  // inviting and then fails -- worse than a Thai chip that works.
  const label = (starter) => {
    const known = {
      'จะไปจากบางนาไปรามคำแหง มีน้ำท่วมไหม': 'chat.s1',
      'น้ำท่วมใกล้ฉันไหม': 'chat.s2',
      'ตอนนี้ท่วมหนักที่ไหน': 'chat.s3',
      'ขอดูกล้อง CCTV ใกล้ฉัน': 'chat.s4',
    }[starter.message]
    return known ? t(known) : starter.label
  }
  const [coords, setCoords] = useState(null)
  // Re-greet in the new language, but only while the greeting is all there
  // is: rewriting a conversation someone is having would lose their place.
  useEffect(() => {
    setMessages((current) =>
      current.length === 1 && current[0].role === 'bot' ? [greeting(t, lang)] : current)
  }, [lang, t])

  const scrollRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    api.chatStarters().then(setStarters).catch(() => setStarters([]))
  }, [])

  useEffect(() => {
    // Ask once, quietly. A refusal just means place-name questions instead.
    if (!navigator.geolocation) return
    navigator.geolocation.getCurrentPosition(
      (position) => setCoords({ lat: position.coords.latitude, lng: position.coords.longitude }),
      () => {},
      { timeout: 8000, maximumAge: 300000 },
    )
  }, [])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, busy])

  const send = async (text) => {
    const message = (text ?? input).trim()
    if (!message || busy) return

    setMessages((previous) => [...previous, { role: 'user', text: message }])
    setInput('')
    setBusy(true)
    try {
      const data = await api.chat({
        message,
        session_id: sessionId,
        lat: coords?.lat,
        lng: coords?.lng,
      })
      setMessages((previous) => [
        ...previous,
        {
          role: 'bot',
          text: data.answer,
          cameras: data.cameras || [],
          route: data.route || null,
          suggestions: data.suggestions || [],
        },
      ])
    } catch (err) {
      setMessages((previous) => [
        ...previous,
        {
          role: 'bot',
          text:
            err instanceof ApiError && err.status === 429
              ? t('chat.tooFast')
              : t('chat.failed'),
          error: true,
        },
      ])
    } finally {
      setBusy(false)
    }
  }

  // A question handed over from elsewhere in the app (e.g. the route panel).
  useEffect(() => {
    if (!pendingMessage) return
    setOpen(true)
    send(pendingMessage)
    onConsumed?.()
  }, [pendingMessage])

  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="group fixed bottom-5 right-4 z-40 flex items-center gap-2.5 rounded-full bg-gradient-to-r from-sky-500 to-indigo-600 py-3 pl-3 pr-4 font-semibold text-white shadow-xl shadow-sky-950/60 ring-2 ring-sky-400/40 transition-transform hover:scale-105 active:scale-95"
        aria-label={t('chat.open')}
      >
        <span className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/15">
          {/* A spark reads as "AI assistant" where a speech bubble reads as
              "customer support" — this answers questions, it is not a helpdesk. */}
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="currentColor" aria-hidden="true">
            <path d="M12 2.5l1.9 4.9 4.9 1.9-4.9 1.9L12 16.1l-1.9-4.9L5.2 9.3l4.9-1.9L12 2.5z" />
            <path d="M18.5 14.2l.9 2.3 2.3.9-2.3.9-.9 2.3-.9-2.3-2.3-.9 2.3-.9.9-2.3z" opacity=".85" />
            <path d="M5.5 14.8l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7.7-1.8z" opacity=".6" />
          </svg>
          <span className="absolute -right-0.5 -top-0.5 flex h-2.5 w-2.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-400 ring-2 ring-slate-950" />
          </span>
        </span>
        <span className="hidden text-sm leading-tight sm:block">
          {t('chat.btn1')}
          <span className="block text-[11px] font-normal text-sky-100/90">
            {t('chat.btn2')}
          </span>
        </span>
      </button>
    )
  }

  return (
    <div className="fixed inset-x-0 bottom-0 z-40 flex h-[82vh] flex-col border-t border-slate-800 bg-slate-950 sm:inset-x-auto sm:bottom-5 sm:right-4 sm:h-[min(36rem,80vh)] sm:w-[25rem] sm:rounded-2xl sm:border">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-sky-500 to-indigo-600">
            <svg viewBox="0 0 24 24" className="h-4 w-4 text-white" fill="currentColor" aria-hidden="true">
              <path d="M12 2.5l1.9 4.9 4.9 1.9-4.9 1.9L12 16.1l-1.9-4.9L5.2 9.3l4.9-1.9L12 2.5z" />
            </svg>
          </span>
          <div>
          <h3 className="text-sm font-bold">{t('chat.title')}</h3>
          <p className="text-xs text-slate-500">
            {coords ? t('chat.knowsLocation') : t('chat.typePlace')}
          </p>
          </div>
        </div>
        <button
          onClick={() => setOpen(false)}
          className="rounded-lg px-2 py-1 text-2xl leading-none text-slate-400 hover:bg-slate-800"
          aria-label={t('chat.close')}
        >
          ×
        </button>
      </div>

      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto p-3">
        {messages.map((message, index) => (
          <div key={index}>
            <div
              className={`max-w-[88%] whitespace-pre-wrap rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed ${
                message.role === 'user'
                  ? 'ml-auto bg-sky-600 text-white'
                  : message.error
                    ? 'bg-red-950 text-red-200'
                    : 'bg-slate-800 text-slate-100'
              }`}
            >
              {message.text}
            </div>

            {message.cameras?.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {message.cameras.slice(0, 6).map((camera) => (
                  <button
                    key={camera.id}
                    onClick={() => onOpenCamera(camera.id)}
                    className="rounded-lg border border-sky-800 bg-sky-950/50 px-2.5 py-1.5 text-xs text-sky-200 hover:bg-sky-900/50"
                  >
                    📹 {camera.name.length > 26 ? `${camera.name.slice(0, 26)}…` : camera.name}
                    {camera.nearby_flood_level && (
                      <span className="ml-1 text-red-300">
                        · {levelLabel(camera.nearby_flood_level)}
                      </span>
                    )}
                  </button>
                ))}
              </div>
            )}

            {message.route && (
              <button
                onClick={() => onShowRoute(message.route)}
                className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-left text-xs text-slate-200 hover:bg-slate-800"
              >
                {t('chat.showRoute')}
              </button>
            )}

            {message.suggestions?.length > 0 && index === messages.length - 1 && !busy && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {message.suggestions.map((suggestion) => (
                  <button
                    key={suggestion.message}
                    onClick={() => send(suggestion.message)}
                    className="rounded-full border border-slate-700 px-3 py-1 text-xs text-slate-300 hover:bg-slate-800"
                  >
                    {label(suggestion)}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}

        {messages.length === 1 && starters.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {starters.map((starter) => (
              <button
                key={starter.message}
                onClick={() => send(starter.message)}
                className="rounded-full border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
              >
                {label(starter)}
              </button>
            ))}
          </div>
        )}

        {busy && (
          <div className="w-16 rounded-2xl bg-slate-800 px-3.5 py-3">
            <span className="flex gap-1">
              {[0, 1, 2].map((dot) => (
                <span
                  key={dot}
                  className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-400"
                  style={{ animationDelay: `${dot * 120}ms` }}
                />
              ))}
            </span>
          </div>
        )}
      </div>

      <form
        className="flex gap-2 border-t border-slate-800 p-3"
        onSubmit={(event) => {
          event.preventDefault()
          send()
        }}
      >
        <input
          ref={inputRef}
          className="field"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder={t('chat.placeholder')}
          disabled={busy}
          maxLength={500}
        />
        <button type="submit" className="btn-primary px-4" disabled={busy || !input.trim()}>
          {t('chat.send')}
        </button>
      </form>
    </div>
  )
}
