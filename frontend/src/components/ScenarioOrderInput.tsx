import { useEffect, useState } from "react";

/** 1-based scenario order; the API stores a 0-based sort_order. */
export function ScenarioOrderInput({
  order,
  onSave,
}: {
  order: number;
  onSave: (order: number) => void;
}) {
  const [value, setValue] = useState(String(order + 1));

  useEffect(() => {
    setValue(String(order + 1));
  }, [order]);

  const commit = () => {
    const parsed = Number.parseInt(value, 10);
    if (!Number.isFinite(parsed) || parsed < 1) {
      setValue(String(order + 1));
      return;
    }
    if (parsed - 1 !== order) {
      onSave(parsed - 1);
    } else {
      setValue(String(order + 1));
    }
  };

  return (
    <label className="scenario-order" title="Scenario order number">
      <span>#</span>
      <input
        type="number"
        min={1}
        inputMode="numeric"
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
          if (event.key === "Escape") {
            setValue(String(order + 1));
            event.currentTarget.blur();
          }
        }}
        onClick={(event) => event.stopPropagation()}
        onMouseDown={(event) => event.stopPropagation()}
        aria-label="Scenario order number"
      />
    </label>
  );
}
