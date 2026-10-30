import Foundation
import Metal

func fail(_ text: String) -> Never {
    fputs("ERROR: \(text)\n", stderr)
    exit(1)
}

let base = FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent("Desktop/NCDR_RESERCH")

let manifestURL = base
    .appendingPathComponent("gpu24/manifest.tsv")

let partsURL = base
    .appendingPathComponent("gpu24/parts")

try FileManager.default.createDirectory(
    at: partsURL,
    withIntermediateDirectories: true
)

let devices = MTLCopyAllDevices()

guard let gpu = devices.first(where: {
    $0.name.contains("Radeon Pro 5500M") ||
    $0.name.contains("Radeon")
}) else {
    fail("AMD Radeon not found")
}

print("SELECTED GPU:", gpu.name)

let metalSource = """
#include <metal_stdlib>
using namespace metal;

kernel void search_metric(
    device const float *dx [[buffer(0)]],
    device const float *dy [[buffer(1)]],
    device const float *yc [[buffer(2)]],
    device float *score [[buffer(3)]],

    constant uint &n [[buffer(4)]],
    constant uint &baseID [[buffer(5)]],
    constant uint &total [[buffer(6)]],
    constant float &sumYY [[buffer(7)]],

    uint tid [[thread_position_in_grid]]
) {
    uint id = baseID + tid;

    if (id >= total) {
        return;
    }

    const uint THETA_N = 360;
    const uint LAMBDA_N = 72;
    const uint P_N = 6;

    uint perP = THETA_N * LAMBDA_N;

    uint pID = id / perP;
    uint rem = id - pID * perP;

    uint lambdaID = rem / THETA_N;
    uint thetaID = rem - lambdaID * THETA_N;

    float theta =
        float(thetaID) *
        3.14159265358979323846f /
        float(THETA_N);

    float t =
        float(lambdaID) /
        float(LAMBDA_N - 1);

    float logMin = log(0.0625f);
    float logMax = log(16.0f);

    float lambda =
        exp(
            logMin +
            t * (logMax - logMin)
        );

    float p;

    if (pID == 0) p = 1.0f;
    else if (pID == 1) p = 1.5f;
    else if (pID == 2) p = 2.0f;
    else if (pID == 3) p = 3.0f;
    else if (pID == 4) p = 4.0f;
    else p = 8.0f;

    float c = cos(theta);
    float s = sin(theta);

    float sx = 0.0f;
    float sxx = 0.0f;
    float sxy = 0.0f;

    for (uint i = 0; i < n; i++) {
        float x = dx[i];
        float y = dy[i];

        float u =
            c*x + s*y;

        float v =
            -s*x + c*y;

        float au = fabs(u);
        float av = fabs(v);

        float m;

        if (pID == 0) {
            m = au + lambda*av;
        }
        else if (pID == 2) {
            m = sqrt(
                au*au +
                lambda*av*av
            );
        }
        else {
            float z =
                pow(au, p) +
                lambda*pow(av, p);

            m = pow(
                max(z, 1e-30f),
                1.0f/p
            );
        }

        sx += m;
        sxx += m*m;
        sxy += m*yc[i];
    }

    float fn = float(n);

    float varX =
        sxx - sx*sx/fn;

    float denom =
        sqrt(
            max(
                varX * sumYY,
                1e-30f
            )
        );

    score[tid] = sxy / denom;
}
"""

let library: MTLLibrary

do {
    library = try gpu.makeLibrary(
        source: metalSource,
        options: nil
    )
}
catch {
    fail("Metal compile: \(error)")
}

guard let function =
    library.makeFunction(name: "search_metric")
else {
    fail("kernel not found")
}

let pipeline: MTLComputePipelineState

do {
    pipeline =
        try gpu.makeComputePipelineState(
            function: function
        )
}
catch {
    fail("pipeline: \(error)")
}

guard let queue = gpu.makeCommandQueue()
else {
    fail("command queue")
}

let manifest = try String(
    contentsOf: manifestURL,
    encoding: .utf8
)

let rows = manifest
    .split(separator: "\n")

print("CLASSES:", rows.count)

let thetaN: UInt32 = 360
let lambdaN: UInt32 = 72
let pN: UInt32 = 6

let totalCandidates =
    thetaN * lambdaN * pN

let batch: UInt32 = 4096

print(
    "CANDIDATES PER CLASS:",
    totalCandidates
)

var classNumber = 0

for rawLine in rows {
    classNumber += 1

    let cols = rawLine.split(
        separator: "\t",
        omittingEmptySubsequences: false
    )

    guard cols.count == 12 else {
        print(
            "SKIP malformed row:",
            cols.count
        )
        continue
    }

    let ident = String(cols[0])

    guard
        let sampleN = UInt32(cols[7]),
        let sumYYd = Double(cols[9])
    else {
        print("SKIP parse:", ident)
        continue
    }

    let binaryPath = String(cols[11])

    let outputURL =
        partsURL.appendingPathComponent(
            ident + ".txt"
        )

    if FileManager.default.fileExists(
        atPath: outputURL.path
    ) {
        print(
            "[\(classNumber)/\(rows.count)]",
            ident,
            "CACHED"
        )
        continue
    }

    let raw = try Data(
        contentsOf:
            URL(fileURLWithPath: binaryPath)
    )

    let n = Int(sampleN)

    let expected =
        4 + n*4*3

    guard raw.count == expected else {
        print(
            "BAD DATA SIZE",
            ident,
            raw.count,
            expected
        )
        continue
    }

    let dxOffset = 4
    let dyOffset = dxOffset + n*4
    let ycOffset = dyOffset + n*4

    let buffers =
        raw.withUnsafeBytes { ptr ->
        (MTLBuffer, MTLBuffer, MTLBuffer) in

        let base = ptr.baseAddress!

        let dx = gpu.makeBuffer(
            bytes:
                base.advanced(by: dxOffset),
            length: n*4,
            options: .storageModeManaged
        )!

        let dy = gpu.makeBuffer(
            bytes:
                base.advanced(by: dyOffset),
            length: n*4,
            options: .storageModeManaged
        )!

        let yc = gpu.makeBuffer(
            bytes:
                base.advanced(by: ycOffset),
            length: n*4,
            options: .storageModeManaged
        )!

        return (dx,dy,yc)
    }

    guard let scoreBuffer =
        gpu.makeBuffer(
            length: Int(batch)*4,
            options: .storageModeManaged
        )
    else {
        fail("score buffer")
    }

    var bestR =
        -Float.greatestFiniteMagnitude

    var bestID: UInt32 = 0

    let started =
        CFAbsoluteTimeGetCurrent()

    var baseID: UInt32 = 0
    var batchNumber = 0

    while baseID < totalCandidates {
        let count =
            min(
                batch,
                totalCandidates-baseID
            )

        guard
            let cb = queue.makeCommandBuffer(),
            let encoder =
                cb.makeComputeCommandEncoder()
        else {
            fail("command creation")
        }

        encoder.setComputePipelineState(
            pipeline
        )

        encoder.setBuffer(
            buffers.0,
            offset: 0,
            index: 0
        )

        encoder.setBuffer(
            buffers.1,
            offset: 0,
            index: 1
        )

        encoder.setBuffer(
            buffers.2,
            offset: 0,
            index: 2
        )

        encoder.setBuffer(
            scoreBuffer,
            offset: 0,
            index: 3
        )

        var nn = sampleN
        var bb = baseID
        var tt = totalCandidates
        var sy = Float(sumYYd)

        encoder.setBytes(
            &nn,
            length: 4,
            index: 4
        )

        encoder.setBytes(
            &bb,
            length: 4,
            index: 5
        )

        encoder.setBytes(
            &tt,
            length: 4,
            index: 6
        )

        encoder.setBytes(
            &sy,
            length: 4,
            index: 7
        )

        let width =
            pipeline.threadExecutionWidth

        let group =
            min(
                pipeline
                    .maxTotalThreadsPerThreadgroup,
                width * 8
            )

        encoder.dispatchThreads(
            MTLSize(
                width: Int(count),
                height: 1,
                depth: 1
            ),
            threadsPerThreadgroup:
                MTLSize(
                    width: group,
                    height: 1,
                    depth: 1
                )
        )

        encoder.endEncoding()

        let blit =
            cb.makeBlitCommandEncoder()!

        blit.synchronize(
            resource: scoreBuffer
        )

        blit.endEncoding()

        cb.commit()
        cb.waitUntilCompleted()

        if let error = cb.error {
            fail(
                "GPU command: \(error)"
            )
        }

        let scores =
            scoreBuffer.contents()
            .bindMemory(
                to: Float.self,
                capacity: Int(batch)
            )

        for i in 0..<Int(count) {
            let r = scores[i]

            if r > bestR {
                bestR = r
                bestID =
                    baseID + UInt32(i)
            }
        }

        baseID += count
        batchNumber += 1

        if batchNumber % 4 == 0 {
            let elapsed =
                CFAbsoluteTimeGetCurrent()
                - started

            let pct =
                100.0 *
                Double(baseID) /
                Double(totalCandidates)

            print(
                "[\(classNumber)/\(rows.count)]",
                ident,
                String(
                    format: "%.1f%%",
                    min(pct,100)
                ),
                "bestR",
                String(
                    format: "%.7f",
                    bestR
                ),
                "elapsed",
                String(
                    format: "%.1fs",
                    elapsed
                )
            )
        }
    }

    let perP =
        thetaN * lambdaN

    let pID =
        bestID / perP

    let rem =
        bestID - pID*perP

    let lambdaID =
        rem / thetaN

    let thetaID =
        rem - lambdaID*thetaN

    let theta =
        Double(thetaID) / 2.0

    let t =
        Double(lambdaID) /
        Double(lambdaN-1)

    let lambda =
        exp(
            log(0.0625) +
            t * (
                log(16.0) -
                log(0.0625)
            )
        )

    let pValues = [
        1.0,
        1.5,
        2.0,
        3.0,
        4.0,
        8.0,
    ]

    let elapsed =
        CFAbsoluteTimeGetCurrent()
        - started

    let result = """
ID\t\(ident)
sample\t\(sampleN)
best_r\t\(bestR)
theta_deg\t\(theta)
lambda\t\(lambda)
p\t\(pValues[Int(pID)])
candidate\t\(bestID)
elapsed_seconds\t\(elapsed)
"""

    try result.write(
        to: outputURL,
        atomically: true,
        encoding: .utf8
    )

    print(
        "[\(classNumber)/\(rows.count)]",
        ident,
        "DONE",
        "R=",
        bestR,
        "theta=",
        theta,
        "lambda=",
        lambda,
        "p=",
        pValues[Int(pID)]
    )
}

print("GPU SEARCH COMPLETE")
