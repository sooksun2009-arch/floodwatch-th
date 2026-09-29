import { useEffect, useState } from 'react'
import { api } from '../api'
import { useT } from '../i18n'

/**
 * Two optional questions -- what the map is used for, and an age range --
 * asked once, after someone has had time to actually use it.
 *
 * Opt-in by construction: fixed choices only (no text box to type a name
 * into), both questions skippable, one "not now" that means never, and the
 * server keeps only a count per answer. The site promises not to profile
 * anyone, and a survey that could be ignored is the only honest way to learn
 * who it is serving.
 */
const ASKED_KEY = 'floodwatch.survey'
const DELAY_MS = 2 * 60 * 1000

const USES = ['commute', 'delivery', 'home', 'agency', 'other']
const AGES = ['u18', '18_24', '25_34', '35_44', '45_54', '55p']

function alreadyAsked() {
  try {
    return Boolean(localStorage.getItem(ASKED_KEY))
  } catch {
    // Storage blocked: we could not remember a "no", so we do not ask at all
    // rather than ask on every visit.
    return true
  }
}

function remember(value) {
  try {
    localStorage.setItem(ASKED_KEY, value)
  } catch {
    /* nothing to do */
  }
}

export default function SurveyCard({ blocked }) {
  const { t } = useT()
  const [due, setDue] = useState(false)
  const [closed, setClosed] = useState(alreadyAsked)
  const [use, setUse] = useState(null)
  const [age, setAge] = useState(null)
  const [thanked, setThanked] = useState(false)

  useEffect(() => {
    if (closed) return undefined
    const timer = setTimeout(() => setDue(true), DELAY_MS)
    return () => clearTimeout(timer)
  }, [closed])

  // Close the thank-you on its own; it has said everything it needs to.
  useEffect(() => {
    if (!thanked) return undefined
    const timer = setTimeout(() => setClosed(true), 2500)
    return () => clearTimeout(timer)
  }, [thanked])

  if (closed || !due || (blocked && !thanked)) return null

  const skip = () => {
    remember('skipped')
    setClosed(true)
  }

  const send = () => {
    remember('answered')
    setThanked(true)
    api.survey({ use, age }).catch(() => {})
  }

  const Choice = ({ value, current, onPick, label }) => (
    <button
      type="button"
      onClick={() => onPick(current === value ? null : value)}
      className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${
        current === value
          ? 'border-sky-400 bg-sky-500/20 text-sky-100'
          : 'border-slate-700 text-slate-300 hover:border-slate-500'
      }`}
    >
      {label}
    </button>
  )

  return (
    <div
      role="dialog"
      aria-label={t('survey.title')}
      className="fixed bottom-3 left-3 right-20 z-30 rounded-2xl border border-slate-700 bg-slate-900/95 p-4 text-sm shadow-2xl backdrop-blur sm:right-auto sm:w-80"
    >
      {thanked ? (
        <p className="text-emerald-300">{t('survey.thanks')}</p>
      ) : (
        <>
          <div className="mb-2 flex items-start justify-between gap-2">
            <p className="font-semibold text-white">{t('survey.title')}</p>
            <button
              onClick={skip}
              aria-label={t('survey.skip')}
              className="-mr-1 -mt-1 px-1 text-lg leading-none text-slate-500 hover:text-slate-300"
            >
              ×
            </button>
          </div>
          <p className="mb-1 text-xs text-slate-400">{t('survey.useQ')}</p>
          <div className="mb-3 flex flex-wrap gap-1.5">
            {USES.map((v) => (
              <Choice key={v} value={v} current={use} onPick={setUse}
                label={t(`survey.use.${v}`)} />
            ))}
          </div>
          <p className="mb-1 text-xs text-slate-400">{t('survey.ageQ')}</p>
          <div className="mb-3 flex flex-wrap gap-1.5">
            {AGES.map((v) => (
              <Choice key={v} value={v} current={age} onPick={setAge}
                label={t(`survey.age.${v}`)} />
            ))}
          </div>
          <div className="flex items-center justify-between gap-2">
            <button onClick={skip} className="text-xs text-slate-400 hover:text-slate-200">
              {t('survey.skip')}
            </button>
            <button
              onClick={send}
              disabled={!use && !age}
              className="rounded-lg bg-sky-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-sky-500 disabled:opacity-40"
            >
              {t('survey.send')}
            </button>
          </div>
          <p className="mt-2 text-[11px] leading-snug text-slate-500">{t('survey.privacy')}</p>
        </>
      )}
    </div>
  )
}
