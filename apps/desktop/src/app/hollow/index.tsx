import { useMemo, useState } from 'react'

import { Codicon } from '@/components/ui/codicon'
import { cn } from '@/lib/utils'
import { notify } from '@/store/notifications'

type ProviderKind = 'llm' | 'voice'
type ProviderStatus = 'sealed' | 'missing'

interface HollowEntry {
  domain: string
  env: string
  kind: ProviderKind
  lane: string
  masked: string
  provider: string
  status: ProviderStatus
}

const ENTRIES: HollowEntry[] = [
  {
    domain: 'openrouter.ai',
    env: 'OPENROUTER_API_KEY',
    kind: 'llm',
    lane: 'Model router',
    masked: 'sealed (masked)',
    provider: 'OpenRouter',
    status: 'sealed'
  },
  {
    domain: 'anthropic.com',
    env: 'ANTHROPIC_API_KEY',
    kind: 'llm',
    lane: 'Claude / Opus',
    masked: 'sealed (masked)',
    provider: 'Anthropic',
    status: 'sealed'
  },
  {
    domain: 'platform.openai.com',
    env: 'OPENAI_API_KEY',
    kind: 'llm',
    lane: 'ChatGPT lane',
    masked: 'sealed (masked)',
    provider: 'OpenAI',
    status: 'sealed'
  },
  {
    domain: 'platform.openai.com',
    env: 'VOICE_TOOLS_OPENAI_KEY',
    kind: 'voice',
    lane: 'STT / TTS',
    masked: 'not sealed',
    provider: 'OpenAI Voice',
    status: 'missing'
  }
]

const FILTERS: Array<{ id: 'all' | ProviderKind; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'llm', label: 'LLM' },
  { id: 'voice', label: 'Voice' }
]

function showToast(title: string, message: string) {
  notify({ kind: 'success', message, title })
}

export function HollowView() {
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<'all' | ProviderKind>('all')
  const [selected, setSelected] = useState<HollowEntry | null>(null)

  const visibleEntries = useMemo(() => {
    const q = query.trim().toLowerCase()

    return ENTRIES.filter(entry => {
      const matchesKind = filter === 'all' || entry.kind === filter

      const matchesQuery =
        !q ||
        [entry.domain, entry.env, entry.lane, entry.masked, entry.provider].some(value =>
          value.toLowerCase().includes(q)
        )

      return matchesKind && matchesQuery
    })
  }, [filter, query])

  const sealedCount = ENTRIES.filter(entry => entry.status === 'sealed').length
  const activeProviders = new Set(ENTRIES.filter(entry => entry.status === 'sealed').map(entry => entry.provider)).size

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden bg-background pt-(--titlebar-height) text-foreground">
      <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-6 py-5">
        <header className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-end">
          <div>
            <div className="font-mono text-[0.68rem] font-bold tracking-[0.18em] text-(--ui-text-secondary) uppercase">
              Nous skin · encrypted local vault
            </div>
            <h1 className="mt-2 text-3xl leading-none font-semibold tracking-[-0.055em] text-primary sm:text-4xl">
              Provider keys, sealed into Hermes.
            </h1>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-(--ui-text-secondary) sm:text-base">
              Hollow fits beside Hermes chat, model switching, cron, and skills: a first-class credential cockpit for
              OpenRouter, Anthropic, OpenAI, and every provider Vision learns to use.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              className="rounded-[6px] border border-(--ui-stroke-secondary) bg-(--ui-bg-tertiary) px-4 py-2 text-sm font-medium text-(--ui-text-primary) hover:bg-(--chrome-action-hover)"
              onClick={() => showToast('Dry run ready', 'Env materialization preview would be shown here.')}
              type="button"
            >
              Dry run
            </button>
            <button
              className="rounded-[6px] bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90"
              onClick={() => showToast('Materialized', 'Selected Hollow keys would be written into the Hermes env.')}
              type="button"
            >
              Materialize selected
            </button>
          </div>
        </header>

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard label="Sealed entries" value={sealedCount} />
          <StatCard label="Active providers" value={activeProviders} />
          <StatCard label="Vault file mode" value="600" />
          <StatCard label="Daily backup" value="03:00" />
        </div>

        <div className="grid min-h-0 gap-4 2xl:grid-cols-[minmax(0,1fr)_20rem]">
          <section className="min-w-0 overflow-hidden rounded-2xl border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary)">
            <div className="grid gap-3 border-b border-(--ui-stroke-tertiary) p-3 lg:grid-cols-[minmax(0,1fr)_auto]">
              <input
                className="min-w-0 rounded-[8px] border border-(--ui-stroke-secondary) bg-(--ui-bg-primary) px-3 py-2 text-sm text-(--ui-text-primary) outline-none placeholder:text-(--ui-text-tertiary) focus:border-ring"
                onChange={event => setQuery(event.target.value)}
                placeholder="Search keys, providers, domains…"
                value={query}
              />
              <div className="flex gap-2">
                {FILTERS.map(item => (
                  <button
                    className={cn(
                      'rounded-[6px] border px-3 py-2 text-xs font-medium transition-colors',
                      filter === item.id
                        ? 'border-(--ui-stroke-secondary) bg-(--ui-control-active-background) text-(--ui-text-primary)'
                        : 'border-(--ui-stroke-tertiary) bg-transparent text-(--ui-text-secondary) hover:bg-(--chrome-action-hover) hover:text-(--ui-text-primary)'
                    )}
                    key={item.id}
                    onClick={() => setFilter(item.id)}
                    type="button"
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full min-w-[48rem] border-collapse text-left">
                <thead>
                  <tr className="border-b border-(--ui-stroke-tertiary) text-[0.68rem] tracking-[0.14em] text-(--ui-text-secondary) uppercase">
                    <th className="px-4 py-3 font-mono font-semibold">Name</th>
                    <th className="px-4 py-3 font-mono font-semibold">Provider</th>
                    <th className="px-4 py-3 font-mono font-semibold">Hermes lane</th>
                    <th className="px-4 py-3 font-mono font-semibold">Masked value</th>
                    <th className="px-4 py-3 font-mono font-semibold">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleEntries.map(entry => (
                    <tr className="border-b border-(--ui-stroke-tertiary) last:border-b-0" key={entry.env}>
                      <td className="px-4 py-4 font-mono text-sm font-medium text-(--ui-text-primary)">{entry.env}</td>
                      <td className="px-4 py-4">
                        <ProviderPill entry={entry} />
                      </td>
                      <td className="px-4 py-4 text-sm text-(--ui-text-primary)">{entry.lane}</td>
                      <td className="px-4 py-4 font-mono text-sm text-(--ui-text-secondary)">{entry.masked}</td>
                      <td className="px-4 py-4">
                        <button
                          className="rounded-[6px] border border-(--ui-stroke-secondary) bg-(--ui-bg-tertiary) px-3 py-1.5 text-xs font-medium text-(--ui-text-primary) hover:bg-(--chrome-action-hover)"
                          onClick={() => setSelected(entry)}
                          type="button"
                        >
                          {entry.status === 'sealed' ? 'Manage' : 'Add'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <aside className="grid gap-4 xl:grid-cols-2 2xl:grid-cols-1">
            <section className="rounded-2xl border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) p-4">
              <div className="mb-4 size-18 rounded-full bg-[radial-gradient(circle_at_38%_35%,#fff_0_8%,var(--theme-primary)_9%_18%,var(--theme-midground)_19%_46%,var(--theme-sidebar-seed)_60%)] shadow-[0_18px_48px_color-mix(in_srgb,var(--theme-midground)_45%,transparent)]" />
              <h2 className="text-base font-semibold text-primary">Hollow status</h2>
              <dl className="mt-3 grid gap-2 text-sm">
                <StatusRow label="Vault" value="encrypted" />
                <StatusRow label="Master key" value="local + secret" />
                <StatusRow label="Git backup" value="safe" />
                <StatusRow label="Reveal mode" value="explicit" />
              </dl>
            </section>

            <section className="rounded-2xl border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) p-4">
              <h2 className="text-base font-semibold text-primary">Hermes workflow</h2>
              <p className="mt-2 text-sm leading-6 text-(--ui-text-secondary)">
                After materializing, use <strong className="font-semibold text-(--ui-text-primary)">/model</strong> to
                switch providers or <strong className="font-semibold text-(--ui-text-primary)">/reload</strong> to refresh
                env-backed credentials in a new session.
              </p>
            </section>

            <section className="overflow-hidden rounded-2xl border border-(--ui-stroke-secondary) bg-(--ui-bg-primary) xl:col-span-2 2xl:col-span-1">
              <div className="flex h-8 items-center gap-1.5 border-b border-(--ui-stroke-tertiary) px-3">
                <span className="size-2.5 rounded-full bg-[#ff6b6b]" />
                <span className="size-2.5 rounded-full bg-[#ffd166]" />
                <span className="size-2.5 rounded-full bg-[#7ef2c7]" />
              </div>
              <pre className="m-0 overflow-x-auto p-4 font-mono text-xs leading-6 text-(--ui-text-secondary)">{`$ hermes hollow list
3 sealed provider keys

$ hermes hollow materialize --dry-run
would update Hermes env safely`}</pre>
            </section>
          </aside>
        </div>
      </div>

      {selected ? <ManageDrawer entry={selected} onClose={() => setSelected(null)} /> : null}
    </section>
  )
}

function StatCard({ label, value }: { label: string; value: number | string }) {
  return (
    <section className="rounded-2xl border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) p-4">
      <div className="text-xs text-(--ui-text-secondary)">{label}</div>
      <div className="mt-2 text-2xl font-semibold tracking-[-0.04em] text-primary">{value}</div>
    </section>
  )
}

function ProviderPill({ entry }: { entry: HollowEntry }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-(--ui-stroke-tertiary) bg-(--ui-bg-tertiary) px-2.5 py-1 text-xs font-medium text-(--ui-text-primary)">
      <span className={cn('size-1.5 rounded-full', entry.status === 'sealed' ? 'bg-emerald-300' : 'bg-amber-300')} />
      {entry.provider}
    </span>
  )
}

function StatusRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-(--ui-text-secondary)">{label}</dt>
      <dd className="font-mono font-semibold text-primary">{value}</dd>
    </div>
  )
}

function ManageDrawer({ entry, onClose }: { entry: HollowEntry; onClose: () => void }) {
  return (
    <div className="fixed right-5 bottom-5 z-50 w-[min(26rem,calc(100vw-2.5rem))] rounded-2xl border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) p-5 shadow-2xl">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold tracking-[-0.03em] text-primary">Manage {entry.env}</h2>
          <p className="mt-2 text-sm leading-6 text-(--ui-text-secondary)">
            The real build should call <code className="font-mono">scripts/hermes-hollow.mjs</code>. Raw values stay
            masked unless the user explicitly requests reveal.
          </p>
        </div>
        <button
          aria-label="Close Hollow key drawer"
          className="grid size-8 shrink-0 place-items-center rounded-[6px] text-(--ui-text-secondary) hover:bg-(--chrome-action-hover) hover:text-(--ui-text-primary)"
          onClick={onClose}
          type="button"
        >
          <Codicon name="close" />
        </button>
      </div>

      <div className="mt-4 grid gap-3">
        <label className="grid gap-1.5 text-xs font-medium text-(--ui-text-secondary)">
          Domain
          <input
            className="rounded-[8px] border border-(--ui-stroke-secondary) bg-(--ui-bg-primary) px-3 py-2 text-sm text-(--ui-text-primary) outline-none focus:border-ring"
            defaultValue={entry.domain}
          />
        </label>
        <label className="grid gap-1.5 text-xs font-medium text-(--ui-text-secondary)">
          Hermes lane
          <input
            className="rounded-[8px] border border-(--ui-stroke-secondary) bg-(--ui-bg-primary) px-3 py-2 text-sm text-(--ui-text-primary) outline-none focus:border-ring"
            defaultValue={entry.lane}
          />
        </label>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          className="rounded-[6px] bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90"
          onClick={() => showToast('Saved encrypted', `${entry.env} would be sealed into Hollow.`)}
          type="button"
        >
          Save encrypted
        </button>
        <button
          className="rounded-[6px] border border-(--ui-stroke-secondary) bg-(--ui-bg-tertiary) px-4 py-2 text-sm font-medium text-(--ui-text-primary) hover:bg-(--chrome-action-hover)"
          onClick={onClose}
          type="button"
        >
          Close
        </button>
      </div>
    </div>
  )
}
