import { Component, OnDestroy, OnInit } from '@angular/core';
import { Subscription } from 'rxjs';
import { LineMeta, TokenSample, TokenUsageService } from '../services/token-usage.service';

interface ChartLine {
  key: string;
  label: string;
  note: string | null;
  color: string;
  visible: boolean;
  path: string;
  points: { x: number; y: number; value: number; ts: string }[];
  latest: number;
  total: number;
}

// Fixed, distinguishable palette -- terminal aesthetic (accent/cyan/magenta/amber
// + a few more hues so all 9 real lines stay tellable apart at a glance).
const PALETTE: { [key: string]: string } = {
  maintenance: '#00ff41',
  morning_briefing: '#ffe066',
  security: '#ff4444',
  newsbot: '#00ccff',
  manager: '#ff00ff',
  cortex: '#ffb000',
  coding_agent: '#7ee787',
  cerebellum_tier3: '#c792ea',
  cerebellum_tier2: '#82aaff',
  watchdog: '#f78c6c',
};

const CHART_W = 760;
const CHART_H = 260;
const PAD_L = 56;
const PAD_R = 12;
const PAD_T = 12;
const PAD_B = 28;

@Component({
  selector: 'app-monitoring',
  templateUrl: 'monitoring.page.html',
  styleUrls: ['monitoring.page.scss'],
  standalone: false,
})
export class MonitoringPage implements OnInit, OnDestroy {
  loading = false;
  error: string | null = null;
  lastRefresh: Date | null = null;

  linesMeta: LineMeta[] = [];
  chartLines: ChartLine[] = [];
  samples: TokenSample[] = [];
  xLabels: { x: number; label: string }[] = [];
  gridLines: { y: number; label: string }[] = [];

  readonly chartW = CHART_W;
  readonly chartH = CHART_H;

  private sub?: Subscription;

  constructor(private tokenUsage: TokenUsageService) {}

  ngOnInit() {
    this.loading = true;
    this.sub = this.tokenUsage.pollUsage().subscribe({
      next: (res) => {
        this.linesMeta = res.lines;
        this.samples = res.samples || [];
        this.rebuildChart();
        this.loading = false;
        this.error = null;
        this.lastRefresh = new Date();
      },
      error: () => {
        this.loading = false;
        this.error = `Token-Usage-API nicht erreichbar (${this.tokenUsage.base})`;
      },
    });
  }

  ngOnDestroy() {
    this.sub?.unsubscribe();
  }

  toggleLine(key: string) {
    const ln = this.chartLines.find((l) => l.key === key);
    if (ln) ln.visible = !ln.visible;
  }

  private rebuildChart() {
    const n = this.samples.length;
    if (n === 0) {
      this.chartLines = this.linesMeta.map((m) => ({
        key: m.key,
        label: m.label,
        note: m.note,
        color: PALETTE[m.key] || '#888',
        visible: true,
        path: '',
        points: [],
        latest: 0,
        total: 0,
      }));
      this.xLabels = [];
      this.gridLines = [];
      return;
    }

    const innerW = CHART_W - PAD_L - PAD_R;
    const innerH = CHART_H - PAD_T - PAD_B;

    let maxVal = 0;
    for (const s of this.samples) {
      for (const m of this.linesMeta) {
        maxVal = Math.max(maxVal, s.values?.[m.key] || 0);
      }
    }
    if (maxVal <= 0) maxVal = 1;

    const xFor = (i: number) => PAD_L + (n === 1 ? innerW / 2 : (i / (n - 1)) * innerW);
    const yFor = (v: number) => PAD_T + innerH - (v / maxVal) * innerH;

    const prevVisible = new Map(this.chartLines.map((l) => [l.key, l.visible]));

    this.chartLines = this.linesMeta.map((m) => {
      const points = this.samples.map((s, i) => ({
        x: xFor(i),
        y: yFor(s.values?.[m.key] || 0),
        value: s.values?.[m.key] || 0,
        ts: s.ts,
      }));
      const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');
      const total = points.reduce((acc, p) => acc + p.value, 0);
      return {
        key: m.key,
        label: m.label,
        note: m.note,
        color: PALETTE[m.key] || '#888',
        visible: prevVisible.has(m.key) ? !!prevVisible.get(m.key) : true,
        path,
        points,
        latest: points.length ? points[points.length - 1].value : 0,
        total,
      };
    });

    // X labels: local HH:mm for every sample (2h grid -> at most 12/day, fits).
    this.xLabels = this.samples.map((s, i) => ({
      x: xFor(i),
      label: this.hhmm(s.ts),
    }));

    // 4 horizontal grid lines (0 .. maxVal).
    const steps = 4;
    this.gridLines = Array.from({ length: steps + 1 }, (_, k) => {
      const v = (maxVal / steps) * k;
      return { y: yFor(v), label: this.fmtTokens(v) };
    });
  }

  hhmm(iso: string): string {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
  }

  fmtTokens(v: number): string {
    if (v >= 1_000_000) return (v / 1_000_000).toFixed(1) + 'M';
    if (v >= 1_000) return (v / 1_000).toFixed(0) + 'k';
    return String(Math.round(v));
  }
}
