declare module "react-cytoscapejs" {
  import type { ComponentType } from "react";

  type CytoscapeComponentProps = {
    elements: Array<Record<string, unknown>>;
    layout?: Record<string, unknown>;
    stylesheet?: Array<Record<string, unknown>>;
    style?: Record<string, string | number>;
    cy?: (cy: unknown) => void;
  };

  const CytoscapeComponent: ComponentType<CytoscapeComponentProps>;
  export default CytoscapeComponent;
}
