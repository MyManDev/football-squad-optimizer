/**
 * Turns the card's SVG into a PNG on the device (#1135 part 3): the SVG is read as a local
 * object URL into an image, drawn on a canvas and saved as a PNG blob. No request leaves the
 * page; the object URL is revoked once the image is drawn.
 */
export async function drawCard(svg: string, width: number, height: number): Promise<Blob> {
  const source = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
  try {
    const image = new Image();
    image.decoding = "async";
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve();
      image.onerror = () => reject(new Error("The card could not be drawn."));
      image.src = source;
    });
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    if (context === null) throw new Error("The card could not be drawn.");
    context.drawImage(image, 0, 0, width, height);
    return await new Promise<Blob>((resolve, reject) =>
      canvas.toBlob(
        (blob) => (blob ? resolve(blob) : reject(new Error("The card could not be drawn."))),
        "image/png",
      ),
    );
  } finally {
    URL.revokeObjectURL(source);
  }
}
