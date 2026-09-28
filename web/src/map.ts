// Map: MapLibre owns the camera; deck.gl draws markers and event arcs through MapboxOverlay (spec §3, §8).
import { Map as MLMap, NavigationControl, type StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { ArcLayer, ScatterplotLayer } from "@deck.gl/layers";
import { feature } from "topojson-client";
import type { GeometryCollection, Topology } from "topojson-specification";
import land50 from "world-atlas/land-50m.json";
import type { EventRec, RelRec } from "./data";
import type { MarkerState } from "./select";

type RGB = [number, number, number];

export const EVENT_COLORS: Record<string, RGB> = {
  battle: [229, 92, 76], siege: [229, 92, 76], war: [229, 92, 76], invasion: [229, 92, 76],
  founded: [110, 196, 140], birth: [150, 160, 175], death: [150, 160, 175],
  synod: [170, 130, 230], council: [170, 130, 230], "ecumenical council": [170, 130, 230],
};
const DEFAULT_COLOR: RGB = [240, 185, 80];

export const colorOf = (ev: EventRec): RGB => {
  const t = ev.eventType.toLowerCase();
  const key = Object.keys(EVENT_COLORS).find((k) => t.includes(k));
  return key ? EVENT_COLORS[key] : DEFAULT_COLOR;
};

/** Keep longitudes continuous along a ring (a jump across ±180° becomes a step past 180°). */
function unwrapRing(ring: GeoJSON.Position[]): GeoJSON.Position[] {
  const out: GeoJSON.Position[] = [];
  let prev = ring[0][0];
  for (const [lon0, lat] of ring) {
    let lon = lon0;
    while (lon - prev > 180) lon -= 360;
    while (lon - prev < -180) lon += 360;
    out.push([lon, lat]);
    prev = lon;
  }
  return out;
}

/** Planar-safe land: unwrap rings that cross the antimeridian (else they smear into bands); drop Antarctica. */
function planarLand(fc: GeoJSON.FeatureCollection | GeoJSON.Feature): GeoJSON.FeatureCollection {
  const feats = "features" in fc ? fc.features : [fc];
  const polys: GeoJSON.Position[][][] = [];
  for (const f of feats) {
    const g = f.geometry;
    const list = g.type === "MultiPolygon" ? g.coordinates : g.type === "Polygon" ? [g.coordinates] : [];
    for (const p of list) {
      if (Math.max(...p[0].map((c) => c[1])) < -55) continue;
      polys.push(p.map(unwrapRing));
    }
  }
  return { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "MultiPolygon", coordinates: polys } }] };
}

function baseStyle(): StyleSpecification {
  const topo = land50 as unknown as Topology<{ land: GeometryCollection }>;
  const land = planarLand(feature(topo, topo.objects.land));
  return {
    version: 8,
    sources: { land: { type: "geojson", data: land } },
    layers: [
      { id: "sea", type: "background", paint: { "background-color": "#0d1117" } },
      { id: "land", type: "fill", source: "land", paint: { "fill-color": "#1b212b" } },
      { id: "coast", type: "line", source: "land", paint: { "line-color": "#384354", "line-width": 0.7 } },
    ],
  };
}

export class MapView {
  readonly map: MLMap;
  private overlay: MapboxOverlay;

  constructor(container: HTMLElement, private onPick: (ev: EventRec) => void) {
    this.map = new MLMap({
      container, style: baseStyle(), center: [8, 47], zoom: 3.6, minZoom: 2, maxZoom: 9,
      attributionControl: { compact: true, customAttribution: "Natural Earth · Wikidata (CC0)" },
    });
    // Overlaid (not interleaved): deck.gl 9.4's interleaved custom layer fails against MapLibre v6's render
    // arguments. MapLibre still owns the camera; deck.gl follows it on a synced canvas.
    this.overlay = new MapboxOverlay({ interleaved: false, layers: [] });
    this.map.addControl(this.overlay);
    this.map.addControl(new NavigationControl({ showCompass: false }), "top-left");
  }

  update(markers: MarkerState[], arcs: { from: EventRec; to: EventRec; rel: RelRec }[]): void {
    const pos = (e: EventRec): [number, number] => [e.location.lon ?? 0, e.location.lat ?? 0];
    this.overlay.setProps({
      layers: [
        new ArcLayer<{ from: EventRec; to: EventRec }>({
          id: "arcs", data: arcs, getSourcePosition: (d) => pos(d.from), getTargetPosition: (d) => pos(d.to),
          getSourceColor: [240, 185, 80, 200], getTargetColor: [229, 92, 76, 200], getWidth: 2, getHeight: 0.4,
        }),
        new ScatterplotLayer<MarkerState>({
          id: "events", data: markers, pickable: true, stroked: true, radiusUnits: "pixels",
          getPosition: (d) => pos(d.ev),
          getRadius: (d) => (d.emphasis === "selected" ? 11 : d.emphasis === "story" ? 7 : 4.5),
          getFillColor: (d) => [...colorOf(d.ev), Math.round(255 * d.opacity)] as [number, number, number, number],
          getLineColor: (d) => (d.emphasis === "selected" ? [255, 255, 255, 255] : [13, 17, 23, Math.round(200 * d.opacity)]),
          getLineWidth: (d) => (d.emphasis === "selected" ? 2 : 1), lineWidthUnits: "pixels",
          onClick: ({ object }) => { if (object) this.onPick(object.ev); },
          updateTriggers: { getFillColor: markers.map((m) => m.opacity), getRadius: markers.map((m) => m.emphasis) },
        }),
      ],
    });
  }

  flyTo(ev: EventRec): void {
    if (ev.location.assessment !== "located") return;
    this.map.flyTo({ center: [ev.location.lon!, ev.location.lat!], zoom: Math.max(this.map.getZoom(), 4.5), speed: 0.9 });
  }
}
