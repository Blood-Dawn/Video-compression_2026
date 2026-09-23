package org.svcs.mobile.detect

import android.content.Context
import android.graphics.Bitmap
import java.io.FileInputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.MappedByteBuffer
import java.nio.channels.FileChannel
import org.tensorflow.lite.Interpreter

/**
 * Thin wrapper over the quantized YOLOv8n LiteRT model bundled as an asset.
 *
 * Fall roadmap Phase 2 ("Smart Compress"): this only answers "was anything
 * worth caring about in this frame", not full detection with boxes and
 * labels - that is the minimum needed to drive the bitrate-adjustment
 * fallback strategy documented in STANDALONE-COMPRESSOR-ROADMAP.md section
 * 4, since true per-region QP control (Android 15's FEATURE_Roi) is
 * OEM-optional and not yet wired through Media3 Transformer's higher-level
 * API - that is real remaining work, not something this class pretends to
 * do.
 *
 * Model provenance: yolov8n.pt -> ONNX -> TFLite, INT8 (dynamic-range)
 * quantized, 320x320 input, exported with
 *   yolo export model=yolov8n.pt format=tflite imgsz=320 int8=True
 * The input tensor stays float32 NHWC despite the INT8 export - only the
 * weights are quantized, so no manual input quantization is needed here.
 *
 * Author: Bloodawn (KheivenD), 2026-09-22 (Fall roadmap Phase 2).
 */
class ObjectDetector(context: Context) : AutoCloseable {
    companion object {
        private const val MODEL_ASSET = "yolov8n_int8.tflite"
        private const val INPUT_SIZE = 320
        // COCO has 80 classes; output rows 4..83 are per-class confidence,
        // rows 0..3 are box coordinates (unused here - presence only).
        private const val NUM_CLASSES = 80
        private const val NUM_ANCHORS = 2100

        /**
         * Deliberately looser than the desktop's 0.35. Measured on the
         * bundled INT8 model: real COCO photos with people/animals score
         * 0.39-0.93 on these classes, while blank, black and pure-noise
         * frames score 0.000-0.005, so 0.25 still separates "empty" from
         * "something there" cleanly. The asymmetry is the point: a false
         * "nothing here" costs the user 35% of their bitrate on a clip that
         * had a person in it, while a false "activity" only forgoes a
         * saving. Err toward detecting.
         */
        private const val CONFIDENCE_THRESHOLD = 0.25f

        /**
         * COCO indices for the same target set the desktop pipeline gates
         * on in src/detection/object_filter.py: people, vehicles, animals,
         * and carried items. Anything else (couch, tv, dining table...) is
         * scenery - a static living room full of furniture is exactly the
         * "nothing happening" footage Smart Compress should squeeze.
         */
        private val TARGET_CLASSES = intArrayOf(
            0, // person
            1, 2, 3, 4, 5, 6, 7, 8, // bicycle car motorcycle airplane bus train truck boat
            14, 15, 16, 17, 18, 19, 20, 21, 22, 23, // bird cat dog horse sheep cow elephant bear zebra giraffe
            24, 26, 28, // backpack handbag suitcase
        )
    }

    private val interpreter: Interpreter = Interpreter(loadModel(context))
    private val inputBuffer = ByteBuffer
        .allocateDirect(4 * INPUT_SIZE * INPUT_SIZE * 3)
        .order(ByteOrder.nativeOrder())
    private val outputBuffer = Array(1) { Array(4 + NUM_CLASSES) { FloatArray(NUM_ANCHORS) } }

    private fun loadModel(context: Context): MappedByteBuffer {
        context.assets.openFd(MODEL_ASSET).use { fd ->
            FileInputStream(fd.fileDescriptor).use { input ->
                return input.channel.map(
                    FileChannel.MapMode.READ_ONLY,
                    fd.startOffset,
                    fd.declaredLength,
                )
            }
        }
    }

    /** True if the model found a person, vehicle, animal or carried item
     *  above [CONFIDENCE_THRESHOLD] in this single frame. The caller owns sampling frequency and cadence -
     *  this only ever looks at the one bitmap it's handed. */
    fun detectsAnything(bitmap: Bitmap): Boolean {
        val resized = if (bitmap.width == INPUT_SIZE && bitmap.height == INPUT_SIZE) {
            bitmap
        } else {
            Bitmap.createScaledBitmap(bitmap, INPUT_SIZE, INPUT_SIZE, true)
        }
        inputBuffer.rewind()
        val pixels = IntArray(INPUT_SIZE * INPUT_SIZE)
        resized.getPixels(pixels, 0, INPUT_SIZE, 0, 0, INPUT_SIZE, INPUT_SIZE)
        for (pixel in pixels) {
            inputBuffer.putFloat(((pixel shr 16) and 0xFF) / 255f)
            inputBuffer.putFloat(((pixel shr 8) and 0xFF) / 255f)
            inputBuffer.putFloat((pixel and 0xFF) / 255f)
        }
        if (resized !== bitmap) resized.recycle()

        interpreter.run(inputBuffer, outputBuffer)

        // Output layout: [1, 84, 2100]; class scores are already
        // sigmoid-activated in the Ultralytics export.
        val scores = outputBuffer[0]
        for (cls in TARGET_CLASSES) {
            val row = scores[4 + cls]
            for (anchor in 0 until NUM_ANCHORS) {
                if (row[anchor] > CONFIDENCE_THRESHOLD) return true
            }
        }
        return false
    }

    override fun close() {
        interpreter.close()
    }
}
