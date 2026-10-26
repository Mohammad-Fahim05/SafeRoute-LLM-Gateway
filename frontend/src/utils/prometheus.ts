export interface PrometheusSample {
  name: string;
  labels: Record<string, string>;
  value: number;
  rawLine: string;
}

export interface PrometheusMetric {
  name: string;
  help: string;
  type: 'counter' | 'gauge' | 'histogram' | 'summary' | 'untyped';
  samples: PrometheusSample[];
  latestValue: number;
}

/**
 * Parses Prometheus exposition text into structured metrics.
 */
export function parsePrometheusText(text: string): PrometheusMetric[] {
  if (!text) return [];

  const lines = text.split('\n');
  const metricMap: Map<string, { help: string; type: PrometheusMetric['type']; samples: PrometheusSample[] }> = new Map();

  let currentHelp = '';
  let currentType: PrometheusMetric['type'] = 'untyped';

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;

    if (trimmed.startsWith('# HELP ')) {
      const parts = trimmed.substring(7).trim().split(/\s+/);
      const name = parts[0];
      currentHelp = parts.slice(1).join(' ');
      if (!metricMap.has(name)) {
        metricMap.set(name, { help: currentHelp, type: 'untyped', samples: [] });
      } else {
        const existing = metricMap.get(name)!;
        existing.help = currentHelp;
      }
      continue;
    }

    if (trimmed.startsWith('# TYPE ')) {
      const parts = trimmed.substring(7).trim().split(/\s+/);
      const name = parts[0];
      const typeStr = (parts[1] || 'untyped').toLowerCase() as PrometheusMetric['type'];
      currentType = ['counter', 'gauge', 'histogram', 'summary'].includes(typeStr) ? typeStr : 'untyped';
      if (!metricMap.has(name)) {
        metricMap.set(name, { help: currentHelp, type: currentType, samples: [] });
      } else {
        const existing = metricMap.get(name)!;
        existing.type = currentType;
      }
      continue;
    }

    if (trimmed.startsWith('#')) {
      continue;
    }

    // Sample line format: metric_name{label1="v1",label2="v2"} 123.45
    // or: metric_name 123.45
    const match = trimmed.match(/^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{([^}]*)\})?\s+([^\s]+)/);
    if (!match) continue;

    const [, fullName, rawLabels, rawValue] = match;
    const value = parseFloat(rawValue);

    // Group histogram/summary buckets into base metric name
    let baseName = fullName;
    if (fullName.endsWith('_bucket') || fullName.endsWith('_sum') || fullName.endsWith('_count')) {
      const candidate = fullName.replace(/_(bucket|sum|count)$/, '');
      if (metricMap.has(candidate)) {
        baseName = candidate;
      }
    }

    // Parse labels
    const labels: Record<string, string> = {};
    if (rawLabels) {
      const labelRegex = /([a-zA-Z_][a-zA-Z0-9_]*)=["']([^"']*)["']/g;
      let labelMatch;
      while ((labelMatch = labelRegex.exec(rawLabels)) !== null) {
        labels[labelMatch[1]] = labelMatch[2];
      }
    }

    const sample: PrometheusSample = {
      name: fullName,
      labels,
      value: isNaN(value) ? 0 : value,
      rawLine: trimmed,
    };

    if (!metricMap.has(baseName)) {
      metricMap.set(baseName, {
        help: currentHelp || 'No description available',
        type: currentType,
        samples: [sample],
      });
    } else {
      metricMap.get(baseName)!.samples.push(sample);
    }
  }

  const result: PrometheusMetric[] = [];
  for (const [name, data] of metricMap.entries()) {
    // Determine latest/representative value
    let latestValue = 0;
    if (data.samples.length > 0) {
      // For histograms/summaries, sum up or pick _count
      const countSample = data.samples.find((s) => s.name.endsWith('_count'));
      if (countSample) {
        latestValue = countSample.value;
      } else {
        latestValue = data.samples.reduce((acc, s) => acc + s.value, 0);
      }
    }

    result.push({
      name,
      help: data.help || 'Prometheus metric exposition sample',
      type: data.type,
      samples: data.samples,
      latestValue,
    });
  }

  // Sort alphabetically by metric name
  return result.sort((a, b) => a.name.localeCompare(b.name));
}
