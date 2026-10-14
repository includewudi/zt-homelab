package net.kaaass.zerotierfix.events;

/**
 * 开关式 orbit/deorbit：只作用于 ZT 节点运行时，不删除数据库条目。
 * 区别于 RemoveMoonOrbitEvent（会删除记录）。
 */
public class ToggleMoonEvent {
    private final long moonWorldId;
    private final long moonSeed;
    private final boolean enabled;

    public ToggleMoonEvent(long moonWorldId, long moonSeed, boolean enabled) {
        this.moonWorldId = moonWorldId;
        this.moonSeed = moonSeed;
        this.enabled = enabled;
    }

    public long getMoonWorldId() {
        return moonWorldId;
    }

    public long getMoonSeed() {
        return moonSeed;
    }

    public boolean isEnabled() {
        return enabled;
    }
}
