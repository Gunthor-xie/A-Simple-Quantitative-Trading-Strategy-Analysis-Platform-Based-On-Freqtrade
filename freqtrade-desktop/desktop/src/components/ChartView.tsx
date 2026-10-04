import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import {
  type CandlestickData,
  ColorType,
  CrosshairMode,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type LogicalRange,
  type UTCTimestamp,
  createChart,
} from "lightweight-charts";
import type { ChartData } from "../types";

interface Props {
  data: ChartData;
  mainIndicators: string[];
  subIndicator: string | null;
  colors?: Partial<ChartStyleConfig>;
}

interface ChartStyleConfig {
  candleUp: string;
  candleDown: string;
  lineWidth: number;
  pnlWidth: number;
  indicatorColors: Record<string, string>;
}

const DEFAULT_COLORS: ChartStyleConfig = {
  candleUp: "#26a69a",
  candleDown: "#ef5350",
  lineWidth: 1,
  pnlWidth: 2,
  indicatorColors: {
    ema144: "#ffb74d",
    ema169: "#4f8cff",
    vwap24: "#26c6da",
    sma20: "#ffb74d",
    ema20: "#4f8cff",
    boll: "#90a4ae",
    boll_upper: "#90a4ae",
    boll_mid: "#607d8b",
    boll_lower: "#90a4ae",
    rsi: "#7e57c2",
    macd: "#4f8cff",
    macdsignal: "#ffb74d",
  },
};

function toLine(times: number[], values: (number | null)[]): LineData[] {
  const out: LineData[] = [];
  values.forEach((value, index) => {
    if (value === null || value === undefined) return;
    out.push({ time: times[index] as UTCTimestamp, value });
  });
  return out;
}

const LINE_COLORS: Record<string, string> = {
  ema144: "#ffb74d",
  ema169: "#4f8cff",
  vwap24: "#26c6da",
  sma20: "#ffb74d",
  ema20: "#4f8cff",
  boll_upper: "#90a4ae",
  boll_mid: "#607d8b",
  boll_lower: "#90a4ae",
  rsi: "#7e57c2",
  macd: "#4f8cff",
  macdsignal: "#ffb74d",
};

interface VisibleRange {
  from: number;
  to: number;
}

/** Minimum width (in %) of the scrollbar thumb so it stays draggable when zoomed in. */
const MIN_WINDOW_PCT = 2;

export default function ChartView({ data, mainIndicators, subIndicator, colors }: Props) {
  const style: ChartStyleConfig = {
    ...DEFAULT_COLORS,
    ...(colors || {}),
    indicatorColors: { ...DEFAULT_COLORS.indicatorColors, ...(colors?.indicatorColors || {}) },
  };
  const mainRef = useRef<HTMLDivElement>(null);
  const subRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const mainChartRef = useRef<IChartApi | null>(null);
  const viewRef = useRef<VisibleRange | null>(null);
  const dragRef = useRef<{
    startX: number;
    startFrom: number;
    width: number;
    barsPerPx: number;
  } | null>(null);
  const frameRef = useRef<number | null>(null);
  const [view, setView] = useState<VisibleRange | null>(null);
  const indicatorKey = mainIndicators.join(",") + "|" + (subIndicator ?? "");
  const totalBars = data.candles.length;

  // Pan the main chart to `from`; the sub chart follows through the range sync.
  const applyWindow = (from: number, width: number) => {
    const chart = mainChartRef.current;
    if (!chart || width <= 0) return;
    const maxFrom = Math.max(0, totalBars - width);
    const nextFrom = Math.min(Math.max(from, 0), maxFrom);
    chart.timeScale().setVisibleLogicalRange({ from: nextFrom, to: nextFrom + width });
  };

  const onScrollPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    const track = scrollRef.current;
    const range = viewRef.current;
    if (!track || !range || totalBars < 2) return;
    const rect = track.getBoundingClientRect();
    if (rect.width <= 0 || range.to - range.from <= 0) return;
    const width = range.to - range.from;
    const barsPerPx = totalBars / rect.width;
    const onWindow = (event.target as HTMLElement).dataset.role === "window";
    // Clicking the empty track jumps that spot to the middle of the window.
    const startFrom = onWindow
      ? range.from
      : (event.clientX - rect.left) * barsPerPx - width / 2;
    dragRef.current = { startX: event.clientX, startFrom, width, barsPerPx };
    track.setPointerCapture(event.pointerId);
    event.preventDefault();
    if (!onWindow) applyWindow(startFrom, width);
  };

  const onScrollPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    applyWindow(drag.startFrom + (event.clientX - drag.startX) * drag.barsPerPx, drag.width);
  };

  const onScrollPointerUp = (event: ReactPointerEvent<HTMLDivElement>) => {
    dragRef.current = null;
    const track = scrollRef.current;
    if (track?.hasPointerCapture(event.pointerId)) track.releasePointerCapture(event.pointerId);
  };

  useEffect(() => {
    if (!mainRef.current) return;
    if (!data || !data.candles || data.candles.length === 0) {
      return;
    }
    const commonLayout = {
      background: { type: ColorType.Solid, color: "#1d2028" },
      textColor: "#9aa0b2",
      fontSize: 11,
    };

    const mainChart: IChartApi = createChart(mainRef.current, {
      width: mainRef.current.clientWidth,
      height: 430,
      layout: commonLayout,
      crosshair: { mode: CrosshairMode.Normal },
      grid: {
        vertLines: { color: "rgba(46,51,66,0.6)" },
        horzLines: { color: "rgba(46,51,66,0.6)" },
      },
      timeScale: { timeVisible: true, secondsVisible: false },
    });
    mainChartRef.current = mainChart;

    const times = data.candles.map((c) => c.time);
    const candleSeries = mainChart.addCandlestickSeries({
      upColor: style.candleUp,
      downColor: style.candleDown,
      borderVisible: false,
      wickUpColor: style.candleUp,
      wickDownColor: style.candleDown,
    });
    const candleData: CandlestickData[] = data.candles.map((c) => ({
      time: c.time as UTCTimestamp,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));
    candleSeries.setData(candleData);

    if (data.markers.length > 0) {
      // Backtest markers already carry the trade id (#12) plus the profit
      // percentage, coloured green for winners and red for losers.
      candleSeries.setMarkers(
        data.markers.map((m) => ({
          time: m.time as UTCTimestamp,
          position: m.position as "aboveBar" | "belowBar",
          color: m.color,
          shape: m.shape as "arrowUp" | "arrowDown" | "circle",
          text: m.text,
        })),
      );
    }

    mainIndicators.forEach((name) => {
      // 布林带在后端返回 boll_upper / boll_mid / boll_lower 三条线，
      // 这里展开绘制；直接取 data.indicators["boll"] 是取不到的。
      if (name === "boll") {
        (["boll_upper", "boll_mid", "boll_lower"] as const).forEach((band) => {
          const values = data.indicators[band];
          if (!values) return;
          const series = mainChart.addLineSeries({
            color: style.indicatorColors[band] ?? LINE_COLORS[band] ?? "#90a4ae",
            lineWidth: Math.min(4, style.lineWidth) as 1 | 2 | 3 | 4,
            priceLineVisible: false,
            lastValueVisible: false,
          });
          series.setData(toLine(times, values));
        });
        return;
      }
      const values = data.indicators[name];
      if (!values) return;
      const series = mainChart.addLineSeries({
        color: style.indicatorColors[name] ?? LINE_COLORS[name] ?? "#b0bec5",
        lineWidth: Math.min(4, style.lineWidth) as 1 | 2 | 3 | 4,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      series.setData(toLine(times, values));
    });

    (data.overlays || []).slice(0, 500).forEach((o) => {
      if (!o.entry || !o.exit) return;
      if (o.entry.time <= 0 || o.exit.time <= 0 || o.entry.price <= 0) return;
      if (o.exit.time <= o.entry.time) return; // open and close inside the same candle
      const line = mainChart.addLineSeries({
        color: o.color,
        lineWidth: Math.min(4, style.pnlWidth) as 1 | 2 | 3 | 4,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      line.setData([
        { time: o.entry.time as UTCTimestamp, value: o.entry.price },
        { time: o.exit.time as UTCTimestamp, value: o.exit.price },
      ]);
    });

    const volumeSeries = mainChart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
      priceLineVisible: false,
      lastValueVisible: false,
    });
    mainChart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });
    const volumeData: HistogramData[] = data.candles.map((c) => ({
      time: c.time as UTCTimestamp,
      value: c.volume,
      color: c.close >= c.open ? "rgba(38,166,154,0.35)" : "rgba(239,83,80,0.35)",
    }));
    volumeSeries.setData(volumeData);

    let subChart: IChartApi | null = null;
    let subSeries: ISeriesApi<"Line"> | null = null;
    if (subIndicator && subRef.current) {
      subChart = createChart(subRef.current, {
        width: subRef.current.clientWidth,
        height: 170,
        layout: commonLayout,
        grid: {
          vertLines: { color: "rgba(46,51,66,0.6)" },
          horzLines: { color: "rgba(46,51,66,0.6)" },
        },
        timeScale: { visible: false },
        rightPriceScale: { borderColor: "rgba(46,51,66,1)" },
      });
      if (subIndicator === "rsi" && data.indicators.rsi) {
        subSeries = subChart.addLineSeries({ color: "#7e57c2", lineWidth: 1 });
        subSeries.setData(toLine(times, data.indicators.rsi));
        subSeries.createPriceLine({
          price: 70,
          color: "rgba(255,255,255,0.3)",
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: false,
          title: "70",
        });
        subSeries.createPriceLine({
          price: 30,
          color: "rgba(255,255,255,0.3)",
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: false,
          title: "30",
        });
      }
      if (subIndicator === "macd") {
        const macdValues = data.indicators.macd;
        const signalValues = data.indicators.macdsignal;
        const histValues = data.indicators.macdhist;
        if (macdValues) {
          const macdSeries = subChart.addLineSeries({ color: "#4f8cff", lineWidth: 1 });
          macdSeries.setData(toLine(times, macdValues));
        }
        if (signalValues) {
          const signalSeries = subChart.addLineSeries({ color: "#ffb74d", lineWidth: 1 });
          signalSeries.setData(toLine(times, signalValues));
        }
        if (histValues) {
          const histSeries = subChart.addHistogramSeries({ priceLineVisible: false });
          const histData: HistogramData[] = [];
          histValues.forEach((value, index) => {
            if (value === null || value === undefined) return;
            histData.push({
              time: times[index] as UTCTimestamp,
              value,
              color: value >= 0 ? "rgba(38,166,154,0.5)" : "rgba(239,83,80,0.5)",
            });
          });
          histSeries.setData(histData);
        }
      }
    }

    // Glue the main and sub time scales together in both directions. Ranges that
    // already match are skipped, so the two handlers cannot ping-pong forever.
    const mirror = (target: IChartApi, range: VisibleRange) => {
      const current = target.timeScale().getVisibleLogicalRange();
      if (
        current &&
        Math.abs(current.from - range.from) < 1e-9 &&
        Math.abs(current.to - range.to) < 1e-9
      ) {
        return;
      }
      target.timeScale().setVisibleLogicalRange({ from: range.from, to: range.to });
    };
    const publish = (range: LogicalRange) => {
      viewRef.current = { from: range.from, to: range.to };
      if (frameRef.current !== null) return;
      frameRef.current = window.requestAnimationFrame(() => {
        frameRef.current = null;
        setView(viewRef.current ? { ...viewRef.current } : null);
      });
    };
    const onMainRange = (range: LogicalRange | null) => {
      if (!range) return;
      publish(range);
      if (subChart) mirror(subChart, range);
    };
    const onSubRange = (range: LogicalRange | null) => {
      if (!range || !subChart) return;
      publish(range);
      mirror(mainChart, range);
    };
    mainChart.timeScale().subscribeVisibleLogicalRangeChange(onMainRange);
    subChart?.timeScale().subscribeVisibleLogicalRangeChange(onSubRange);

    mainChart.timeScale().fitContent();
    const fitted = mainChart.timeScale().getVisibleLogicalRange();
    if (fitted) {
      publish(fitted);
      if (subChart) mirror(subChart, fitted);
    }

    // Matching price scale width keeps the two panes aligned pixel for pixel.
    if (subChart) {
      const priceWidth = Math.round(
        mainChart.priceScale("right").width() + mainChart.priceScale("vol").width(),
      );
      if (priceWidth > 0) {
        subChart.applyOptions({ rightPriceScale: { minimumWidth: priceWidth } });
      }
    }

    const handleResize = () => {
      if (!mainRef.current) return;
      mainChart.applyOptions({ width: mainRef.current.clientWidth });
      if (subChart && subRef.current) {
        subChart.applyOptions({ width: subRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      if (frameRef.current !== null) {
        window.cancelAnimationFrame(frameRef.current);
        frameRef.current = null;
      }
      mainChart.timeScale().unsubscribeVisibleLogicalRangeChange(onMainRange);
      subChart?.timeScale().unsubscribeVisibleLogicalRangeChange(onSubRange);
      mainChartRef.current = null;
      mainChart.remove();
      subChart?.remove();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, indicatorKey]);

  // Thumb geometry: the width mirrors the visible slice, so zooming in the main
  // chart shrinks it, while dragging the thumb only pans (never zooms).
  const scrollWindow = (() => {
    if (!view || totalBars < 2) return { left: 0, width: 100 };
    const from = Math.min(Math.max(view.from, 0), totalBars);
    const to = Math.min(Math.max(view.to, 0), totalBars);
    const width = Math.min(100, Math.max(MIN_WINDOW_PCT, ((to - from) / totalBars) * 100));
    const left = Math.min(Math.max((from / totalBars) * 100, 0), 100 - width);
    return { left, width };
  })();

  return (
    <div>
      {data.coverage && (
        <div className="hint" style={{ marginBottom: 6 }}>
          数据覆盖：{new Date(data.coverage.start).toISOString().slice(0, 10)} ~{" "}
          {new Date(data.coverage.end).toISOString().slice(0, 10)}（{data.coverage.count} 根，
          完整性 {(data.coverage.fill_ratio * 100).toFixed(1)}%
          {data.coverage.has_gap ? "，存在缺口" : ""}）
        </div>
      )}
      <div ref={mainRef} className="chart-container" />
      <div
        ref={scrollRef}
        className="chart-scrollbar"
        title="拖动可快速平移图表（滑块本身不缩放）"
        onPointerDown={onScrollPointerDown}
        onPointerMove={onScrollPointerMove}
        onPointerUp={onScrollPointerUp}
        onPointerCancel={onScrollPointerUp}
        onLostPointerCapture={onScrollPointerUp}
      >
        <div
          className="chart-scrollbar-window"
          data-role="window"
          style={{ left: `${scrollWindow.left}%`, width: `${scrollWindow.width}%` }}
        />
      </div>
      {subIndicator && <div ref={subRef} className="chart-container" style={{ marginTop: 8 }} />}
    </div>
  );
}
