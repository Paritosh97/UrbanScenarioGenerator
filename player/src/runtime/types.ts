export type Pt = [number, number];

export interface RoadRec {
  id: string; osm_way: number; name: string; hclass: string; pts: Pt[]; lanes: number; width: number;
  oneway: boolean; speed: number; sidewalk_left: number; sidewalk_right: number;
  start_node: string; end_node: string; trim_start: number; trim_end: number;
}
export interface JunctionRec {
  id: string; pos: Pt; roads: string[]; radius: number; signalized: boolean; signal_id: string | null;
  polygon: Pt[]; corners: Pt[][];
}
export interface CrossingRec {
  id: string; road: string; s: number; pos: Pt; heading: number; length: number; width: number;
  control: 'zebra' | 'signals' | 'uncontrolled'; signal_id: string | null;
}
export interface SignalRec { id: string; pos: Pt; road: string | null; kind: 'vehicle' | 'pedestrian'; crossing: string | null }
export interface PropRec { id: string; ptype: string; pos: Pt; heading: number; road: string | null; name: string }
export interface BuildingRec { id: string; pts: Pt[]; height: number; name: string }
export interface BarrierRec { id: string; pts: Pt[]; height: number; btype: string }
export interface AreaRec { id: string; atype: 'water' | 'green'; pts: Pt[] }
export interface PathRec { id: string; pts: Pt[]; width: number; ptype: string }
export interface RailwayRec { id: string; pts: Pt[]; rtype: string }

/** scene_map.json written by the Python exporter. One metric ENU frame (x east, y north, metres). */
export interface SceneMap {
  format: string;
  origin: { lat: number; lon: number };
  bounds: [number, number, number, number];
  roads: RoadRec[];
  junctions: JunctionRec[];
  crossings: CrossingRec[];
  signals: SignalRec[];
  props: PropRec[];
  buildings: BuildingRec[];
  barriers: BarrierRec[];
  areas: AreaRec[];
  paths: PathRec[];
  railways: RailwayRec[];
}

export type Surface = 'road' | 'crosswalk' | 'sidewalk' | 'path' | 'building' | 'water' | 'ground';

export interface ScenarioPackage {
  format: 'usg-scenario-package/1';
  name: string;
  map: SceneMap;
  xosc: string;
  spec: unknown;
  script: string;
  plan: unknown;
  issues: { severity: string; code: string; message: string }[];
}
