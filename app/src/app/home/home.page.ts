import { Component, OnInit } from '@angular/core';
import { NabuService, Schedule, EngineStatus, EntityStats } from '../services/nabu.service';

@Component({
  selector: 'app-home',
  templateUrl: 'home.page.html',
  styleUrls: ['home.page.scss'],
  standalone: false,
})
export class HomePage implements OnInit {
  schedule: Schedule | null = null;
  status: EngineStatus | null = null;
  entities: EntityStats[] = [];
  loading = false;
  activeTab: 'so_do' | 'fr_sa' = 'so_do';
  activeType: 'licht' | 'musik' = 'licht';
  lastRefresh: Date | null = null;

  readonly zones = ['flur', 'pc', 'bett'];
  readonly slotOrder = [
    'sunset', '12:00', '17:00', '17:30', '18:00', '19:00', '20:00',
    '21:00', '21:30', '22:00', '22:30', '23:00', '00:00', '01:00', '02:00'
  ];

  constructor(private nabu: NabuService) {}

  ngOnInit() {
    this.refresh();
    const wd = new Date().getDay();
    this.activeTab = (wd === 5 || wd === 6) ? 'fr_sa' : 'so_do';
  }

  refresh() {
    this.loading = true;
    this.nabu.getSchedule().subscribe({
      next: (data) => {
        this.schedule = data;
        this.lastRefresh = new Date();
        this.loading = false;
      },
      error: () => { this.loading = false; }
    });
    this.nabu.getStatus().subscribe({
      next: (data) => { this.status = data; }
    });
    this.nabu.getEntities().subscribe({
      next: (data) => { this.entities = data; }
    });
  }

  // Entity stats helpers
  getMaxTotal(): number {
    return this.entities.length > 0 ? this.entities[0].total : 1;
  }

  getBarWidth(e: EntityStats): number {
    return Math.max(2, (e.total / this.getMaxTotal()) * 100);
  }

  getEntityShortName(entity: string): string {
    if (entity.startsWith('musik:')) return entity;
    return entity.split('.').pop() || entity;
  }

  getEntityType(entity: string): string {
    if (entity.startsWith('musik:')) return 'musik';
    if (entity.startsWith('light.')) return 'licht';
    if (entity.startsWith('switch.')) return 'switch';
    return 'other';
  }

  getEntityColor(e: EntityStats): string {
    const type = this.getEntityType(e.entity);
    if (type === 'musik') return '#ff00ff';
    if (type === 'switch') return '#ffb000';
    if (e.last_state === 'on') return '#00ff41';
    if (e.last_state === 'off') return '#333';
    return '#00ff41';
  }

  getLastTimeShort(time: string | null): string {
    if (!time) return '-';
    const parts = time.split(' ');
    return parts.length > 1 ? parts[1].substring(0, 8) : time;
  }

  // Schedule helpers
  getLichtSlots(): string[] {
    if (!this.schedule) return [];
    const dayData = this.schedule.licht[this.activeTab] || {};
    return this.slotOrder.filter(s => s in dayData);
  }

  getMusikSlots(): string[] {
    if (!this.schedule) return [];
    const dayData = this.schedule.musik[this.activeTab] || {};
    return this.slotOrder.filter(s => s in dayData);
  }

  getZoneEntities(slot: string, zone: string): { name: string; state: string; brightness?: number; color?: string; kelvin?: number }[] {
    if (!this.schedule) return [];
    const zoneData = this.schedule.licht[this.activeTab]?.[slot]?.[zone];
    if (!zoneData) return [];
    return Object.entries(zoneData).map(([entity, attrs]: [string, any]) => ({
      name: entity.split('.').pop() || entity,
      state: attrs.state,
      brightness: attrs.brightness_pct,
      color: attrs.rgb_color ? `rgb(${attrs.rgb_color.join(',')})` : undefined,
      kelvin: attrs.color_temp_kelvin,
    }));
  }

  getMusikSlot(slot: string): any {
    return this.schedule?.musik[this.activeTab]?.[slot];
  }

  getZoneDominantColor(slot: string, zone: string): string {
    const entities = this.getZoneEntities(slot, zone);
    const on = entities.find(e => e.state === 'on' && e.color);
    if (on?.color) return on.color;
    const kelvin = entities.find(e => e.state === 'on' && e.kelvin);
    if (kelvin) return 'rgb(255, 200, 120)';
    const allOff = entities.every(e => e.state === 'off');
    if (allOff && entities.length > 0) return 'rgb(30, 30, 30)';
    return 'transparent';
  }

  getActiveZones(): { zone: string; entities: { name: string; state: string }[] }[] {
    if (!this.status?.zone_states) return [];
    return Object.entries(this.status.zone_states)
      .filter(([zone]) => zone !== 'none')
      .map(([zone, entities]: [string, any]) => ({
        zone,
        entities: Object.entries(entities).map(([entity, st]: [string, any]) => ({
          name: entity.split('.').pop() || entity,
          state: st?.state || 'off',
        })),
      }));
  }

  getLogLines(): string[] {
    if (!this.status?.logs) return [];
    return this.status.logs.map(l => {
      const match = l.match(/(\d{2}:\d{2}:\d{2})\.\d+ INFO nabu_engine: (.*)/);
      return match ? `${match[1]} ${match[2]}` : l.substring(Math.max(0, l.length - 70));
    });
  }
}
