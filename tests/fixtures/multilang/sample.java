package com.example.town;

import java.util.List;

public class TownManager extends BaseManager implements Saveable {

    public TownManager(List<String> towns) {
        this.towns = towns;
    }

    public Town createTown(String name) {
        return register(name);
    }

    public boolean removeTown(String name) {
        return unregister(name);
    }
}
