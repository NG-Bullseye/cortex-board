import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface LichtSlot {
  [entity: string]: {
    state: string;
    brightness_pct?: number;
    rgb_color?: number[];
    color_temp_kelvin?: number;
  };
}

export interface MusikSlot {
  name: string;
  uris: string[];
  shuffle: boolean;
}

export interface Schedule {
  licht: {
    [day: string]: {
      [slot: string]: {
        [zone: string]: LichtSlot;
      };
    };
  };
  musik: {
    [day: string]: {
      [slot: string]: MusikSlot;
    };
  };
}

export interface EngineStatus {
  zone_states: any;
  logs: string[];
  config: { [key: string]: number };
}

export interface EntityStats {
  entity: string;
  on: number;
  off: number;
  total: number;
  last_state: string;
  last_time: string;
}

@Injectable({ providedIn: 'root' })
export class NabuService {
  private baseUrl = '';

  constructor(private http: HttpClient) {}

  getSchedule(): Observable<Schedule> {
    return this.http.get<Schedule>(`${this.baseUrl}/api/schedule`);
  }

  getStatus(): Observable<EngineStatus> {
    return this.http.get<EngineStatus>(`${this.baseUrl}/api/status`);
  }

  getEntities(): Observable<EntityStats[]> {
    return this.http.get<EntityStats[]>(`${this.baseUrl}/api/entities`);
  }
}
