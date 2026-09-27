import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../api'
import { useAuth } from '../auth'

export default function Login() {
  const { login, register, user } = useAuth()
  const navigate = useNavigate()
  const [mode, setMode] = useState('login')
  const [form, setForm] = useState({ username: '', password: '', display_name: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  if (user) {
    navigate('/', { replace: true })
    return null
  }

  const set = (key) => (event) => setForm({ ...form, [key]: event.target.value })

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (mode === 'login') await login(form.username, form.password)
      else
        await register({
          username: form.username,
          password: form.password,
          display_name: form.display_name || form.username,
        })
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'ดำเนินการไม่สำเร็จ')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto max-w-sm p-4 pt-10">
      <div className="card p-5">
        <h1 className="text-lg font-bold">
          {mode === 'login' ? 'เข้าสู่ระบบ' : 'สมัครบัญชีผู้ใช้'}
        </h1>
        <p className="mt-1 text-sm text-slate-400">
          แจ้งน้ำท่วมได้โดยไม่ต้องล็อกอิน — บัญชีมีไว้ให้ติดตามรายงานของตัวเอง
          และให้เจ้าหน้าที่ใช้สิทธิ์ผู้ดูแล
        </p>

        <form onSubmit={submit} className="mt-4 space-y-3">
          <div>
            <label className="label" htmlFor="username">
              ชื่อผู้ใช้
            </label>
            <input
              id="username"
              className="field"
              value={form.username}
              onChange={set('username')}
              autoComplete="username"
              required
              minLength={3}
            />
          </div>

          {mode === 'register' && (
            <div>
              <label className="label" htmlFor="display_name">
                ชื่อที่แสดง
              </label>
              <input
                id="display_name"
                className="field"
                value={form.display_name}
                onChange={set('display_name')}
              />
            </div>
          )}

          <div>
            <label className="label" htmlFor="password">
              รหัสผ่าน
            </label>
            <input
              id="password"
              type="password"
              className="field"
              value={form.password}
              onChange={set('password')}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              required
              minLength={8}
            />
            {mode === 'register' && (
              <p className="mt-1 text-xs text-slate-500">อย่างน้อย 8 ตัวอักษร</p>
            )}
          </div>

          {error && (
            <p className="rounded-xl border border-red-900 bg-red-950/50 px-3 py-2 text-sm text-red-300">
              {error}
            </p>
          )}

          <button type="submit" className="btn-primary w-full" disabled={busy}>
            {busy ? 'กำลังดำเนินการ…' : mode === 'login' ? 'เข้าสู่ระบบ' : 'สมัครบัญชี'}
          </button>
        </form>

        <button
          onClick={() => {
            setMode(mode === 'login' ? 'register' : 'login')
            setError(null)
          }}
          className="mt-4 w-full text-sm text-slate-400 hover:text-slate-200"
        >
          {mode === 'login' ? 'ยังไม่มีบัญชี? สมัครที่นี่' : 'มีบัญชีอยู่แล้ว? เข้าสู่ระบบ'}
        </button>
      </div>
    </div>
  )
}
