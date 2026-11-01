// A small JSON Schema reader for the tests: enough of draft 2020-12 to check the forwarder's
// documents against the committed schemas in docs/contracts without a dependency.
//
// It knows the keywords those schemas use and refuses any other, so a schema that grows a
// keyword this file does not read fails loudly instead of passing everything. The Python test
// tests/unit/test_fpl_forwarder_contracts.py checks the same schemas and examples with
// jsonschema itself.

import { readFile } from "node:fs/promises";

const REPOSITORY = new URL("../../../", import.meta.url);

export async function contractFile(name) {
  return JSON.parse(await readFile(new URL(`docs/contracts/${name}`, REPOSITORY), "utf8"));
}

const ANNOTATIONS = new Set(["$schema", "title", "description", "$defs", "$comment"]);
const KEYWORDS = new Set([
  "$ref",
  "anyOf",
  "const",
  "enum",
  "type",
  "required",
  "properties",
  "additionalProperties",
  "items",
  "minItems",
  "maxItems",
  "uniqueItems",
  "minimum",
  "maximum",
  "pattern",
  "minLength",
]);

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function typeMatches(type, value) {
  switch (type) {
    case "object":
      return isObject(value);
    case "array":
      return Array.isArray(value);
    case "string":
      return typeof value === "string";
    case "boolean":
      return typeof value === "boolean";
    case "null":
      return value === null;
    case "number":
      return typeof value === "number" && Number.isFinite(value);
    case "integer":
      return typeof value === "number" && Number.isInteger(value);
    default:
      throw new Error(`unknown type ${type}`);
  }
}

const same = (left, right) => JSON.stringify(left) === JSON.stringify(right);

/** Every way `value` fails `schema`, as "path: reason" lines; an empty list means it passes. */
export function problems(schema, value, root = schema, path = "$") {
  if (schema === true) return [];
  if (schema === false) return [`${path}: nothing is allowed here`];
  for (const key of Object.keys(schema)) {
    if (!KEYWORDS.has(key) && !ANNOTATIONS.has(key)) {
      throw new Error(`the test reader does not know the keyword ${key} (at ${path})`);
    }
  }
  const found = [];
  if (schema.$ref !== undefined) {
    const match = /^#\/\$defs\/([A-Za-z0-9_]+)$/.exec(schema.$ref);
    if (match === null || root.$defs?.[match[1]] === undefined) {
      throw new Error(`cannot follow ${schema.$ref}`);
    }
    found.push(...problems(root.$defs[match[1]], value, root, path));
  }
  if (schema.anyOf !== undefined) {
    const passes = schema.anyOf.some((option) => problems(option, value, root, path).length === 0);
    if (!passes) found.push(`${path}: matches none of anyOf`);
  }
  if (schema.const !== undefined && !same(schema.const, value)) {
    found.push(`${path}: is not ${JSON.stringify(schema.const)}`);
  }
  if (schema.enum !== undefined && !schema.enum.some((option) => same(option, value))) {
    found.push(`${path}: is not one of ${JSON.stringify(schema.enum)}`);
  }
  if (schema.type !== undefined) {
    const types = Array.isArray(schema.type) ? schema.type : [schema.type];
    if (!types.some((type) => typeMatches(type, value))) {
      found.push(`${path}: is not of type ${types.join(" or ")}`);
      return found;
    }
  }
  if (isObject(value)) {
    for (const key of schema.required ?? []) {
      if (!Object.hasOwn(value, key)) found.push(`${path}: lacks ${key}`);
    }
    const properties = schema.properties ?? {};
    for (const [key, item] of Object.entries(value)) {
      if (Object.hasOwn(properties, key)) {
        found.push(...problems(properties[key], item, root, `${path}.${key}`));
      } else if (schema.additionalProperties === false) {
        found.push(`${path}: has a field it may not have, ${key}`);
      } else if (isObject(schema.additionalProperties)) {
        found.push(...problems(schema.additionalProperties, item, root, `${path}.${key}`));
      }
    }
  }
  if (Array.isArray(value)) {
    if (schema.items !== undefined) {
      value.forEach((item, index) => {
        found.push(...problems(schema.items, item, root, `${path}[${index}]`));
      });
    }
    if (schema.minItems !== undefined && value.length < schema.minItems) {
      found.push(`${path}: has fewer than ${schema.minItems} items`);
    }
    if (schema.maxItems !== undefined && value.length > schema.maxItems) {
      found.push(`${path}: has more than ${schema.maxItems} items`);
    }
    if (
      schema.uniqueItems === true &&
      new Set(value.map((item) => JSON.stringify(item))).size !== value.length
    ) {
      found.push(`${path}: repeats an item`);
    }
  }
  if (typeof value === "number") {
    if (schema.minimum !== undefined && value < schema.minimum) {
      found.push(`${path}: is below ${schema.minimum}`);
    }
    if (schema.maximum !== undefined && value > schema.maximum) {
      found.push(`${path}: is above ${schema.maximum}`);
    }
  }
  if (typeof value === "string") {
    if (schema.pattern !== undefined && !new RegExp(schema.pattern, "u").test(value)) {
      found.push(`${path}: does not match ${schema.pattern}`);
    }
    if (schema.minLength !== undefined && [...value].length < schema.minLength) {
      found.push(`${path}: is shorter than ${schema.minLength}`);
    }
  }
  return found;
}
