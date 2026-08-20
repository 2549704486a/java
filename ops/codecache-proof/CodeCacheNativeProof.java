import java.util.ArrayList;
import java.util.List;

public class CodeCacheNativeProof {
    private static volatile long sink = 0L;

    public static void main(String[] args) throws Exception {
        long pid = ProcessHandle.current().pid();
        System.out.println("PID=" + pid);
        System.out.println("PHASE=cold");
        System.out.println("ACTION=take_cold_snapshots");
        Thread.sleep(60000L);

        long warmupStart = System.currentTimeMillis();
        runWarmup();
        long warmupMs = System.currentTimeMillis() - warmupStart;

        System.out.println("WARMUP_MS=" + warmupMs);
        System.out.println("SINK=" + sink);
        System.out.println("PHASE=hot");
        System.out.println("ACTION=take_hot_snapshots");
        Thread.sleep(60000L);
    }

    private static void runWarmup() {
        List<IntWorker> workers = buildWorkers();
        for (int round = 0; round < 120; round++) {
            for (int i = 0; i < 500_000; i++) {
                IntWorker worker = workers.get(i % workers.size());
                sink += worker.apply(i);
            }
        }
    }

    private static List<IntWorker> buildWorkers() {
        List<IntWorker> workers = new ArrayList<>();
        workers.add(CodeCacheNativeProof::hot01);
        workers.add(CodeCacheNativeProof::hot02);
        workers.add(CodeCacheNativeProof::hot03);
        workers.add(CodeCacheNativeProof::hot04);
        workers.add(CodeCacheNativeProof::hot05);
        workers.add(CodeCacheNativeProof::hot06);
        workers.add(CodeCacheNativeProof::hot07);
        workers.add(CodeCacheNativeProof::hot08);
        workers.add(CodeCacheNativeProof::hot09);
        workers.add(CodeCacheNativeProof::hot10);
        workers.add(CodeCacheNativeProof::hot11);
        workers.add(CodeCacheNativeProof::hot12);
        workers.add(CodeCacheNativeProof::hot13);
        workers.add(CodeCacheNativeProof::hot14);
        workers.add(CodeCacheNativeProof::hot15);
        workers.add(CodeCacheNativeProof::hot16);
        return workers;
    }

    private static long hot01(int x) { return ((long) x * 31 + 7) ^ (x >>> 3); }
    private static long hot02(int x) { return Integer.rotateLeft(x, 5) + (x % 17L); }
    private static long hot03(int x) { return (x * 13L) - (x / 7L) + (x & 63L); }
    private static long hot04(int x) { return ((x << 2) ^ (x * 97L)) + (x >>> 5); }
    private static long hot05(int x) { return ((x % 29L) * (x % 31L)) + (x >>> 2); }
    private static long hot06(int x) { return (x * 101L) ^ ((long) x * x); }
    private static long hot07(int x) { return (x / 3L) + ((x & 255L) * 19L); }
    private static long hot08(int x) { return Integer.reverse(x) ^ (x * 43L); }
    private static long hot09(int x) { return (x * 17L) + (x * 19L) - (x % 11L); }
    private static long hot10(int x) { return (x >>> 1) + (x >>> 2) + (x >>> 3); }
    private static long hot11(int x) { return (x * 67L) ^ (x << 11) ^ (x >>> 7); }
    private static long hot12(int x) { return ((x & 1023L) * (x & 511L)) + 3L; }
    private static long hot13(int x) { return (long) (x % 37) * 73 + (x / 5L); }
    private static long hot14(int x) { return ((x * 257L) >>> 4) ^ (x * 13L); }
    private static long hot15(int x) { return ((x << 6) - x) + (x % 97L); }
    private static long hot16(int x) { return (x * 3L) + (x * 5L) + (x * 7L); }

    @FunctionalInterface
    private interface IntWorker {
        long apply(int value);
    }
}
