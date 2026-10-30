import Foundation
import Metal

let devices = MTLCopyAllDevices()

print("Metal devices:")
for d in devices {
    print(" - \(d.name), lowPower=\(d.isLowPower), removable=\(d.isRemovable)")
}

guard let gpu = devices.first(where: {
    $0.name.contains("5500M") ||
    $0.name.contains("Radeon")
}) else {
    print("ERROR: AMD Radeon not found")
    exit(2)
}

print("SELECTED:", gpu.name)

let source = """
#include <metal_stdlib>
using namespace metal;

kernel void gpu_probe(
    device const float *input [[buffer(0)]],
    device float *output [[buffer(1)]],
    uint id [[thread_position_in_grid]]
) {
    float x = input[id];

    for (uint k = 0; k < 256; ++k) {
        x = sqrt(x * x + 0.000001f);
        x = fma(x, 1.000001f, 0.000001f);
    }

    output[id] = x;
}
"""

let library = try gpu.makeLibrary(
    source: source,
    options: nil
)

guard let fn = library.makeFunction(
    name: "gpu_probe"
) else {
    fatalError("kernel missing")
}

let pipeline = try gpu.makeComputePipelineState(
    function: fn
)

let n = 4 * 1024 * 1024
let bytes = n * MemoryLayout<Float>.stride

guard
    let input = gpu.makeBuffer(
        length: bytes,
        options: .storageModeManaged
    ),
    let output = gpu.makeBuffer(
        length: bytes,
        options: .storageModeManaged
    )
else {
    fatalError("buffer allocation failed")
}

let p = input.contents().bindMemory(
    to: Float.self,
    capacity: n
)

for i in 0..<n {
    p[i] = Float(i % 1000) / 1000.0 + 0.001
}

input.didModifyRange(0..<bytes)

guard
    let queue = gpu.makeCommandQueue(),
    let cb = queue.makeCommandBuffer(),
    let enc = cb.makeComputeCommandEncoder()
else {
    fatalError("command creation failed")
}

enc.setComputePipelineState(pipeline)
enc.setBuffer(input, offset: 0, index: 0)
enc.setBuffer(output, offset: 0, index: 1)

let width = pipeline.threadExecutionWidth
let maxThreads = pipeline.maxTotalThreadsPerThreadgroup
let group = min(maxThreads, width * 8)

enc.dispatchThreads(
    MTLSize(width: n, height: 1, depth: 1),
    threadsPerThreadgroup:
        MTLSize(width: group, height: 1, depth: 1)
)

enc.endEncoding()

let blit = cb.makeBlitCommandEncoder()!
blit.synchronize(resource: output)
blit.endEncoding()

let t0 = CFAbsoluteTimeGetCurrent()

cb.commit()
cb.waitUntilCompleted()

let elapsed = CFAbsoluteTimeGetCurrent() - t0

if let err = cb.error {
    print("GPU ERROR:", err)
    exit(3)
}

let result = output.contents()
    .bindMemory(
        to: Float.self,
        capacity: n
    )

print("GPU OK")
print("Elapsed:", String(format: "%.3f", elapsed), "sec")
print("Sample:", result[0], result[n/2], result[n-1])
