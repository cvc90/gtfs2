"""Data Update coordinator for the GTFS integration."""
from __future__ import annotations

import datetime
from datetime import timedelta
import logging


from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
import homeassistant.util.dt as dt_util

from .const import (
    DEFAULT_PATH, 
    DEFAULT_REFRESH_INTERVAL, 
    CONF_API_KEY, 
    CONF_X_API_KEY,
    ATTR_DUE_IN,
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
    ATTR_RT_UPDATED_AT
)    
from .gtfs_helper import get_gtfs, get_next_departure, check_datasource_index
from .gtfs_rt_helper import get_rt_route_statuses, get_next_services

_LOGGER = logging.getLogger(__name__)


class GTFSUpdateCoordinator(DataUpdateCoordinator):
    """Data update coordinator for the GTFS integration."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name=entry.entry_id,
            update_interval=timedelta(minutes=1),
        )
        self.config_entry = entry
        self.hass = hass
        
        self._pygtfs = ""
        self._data: dict[str, str] = {}

    async def _async_update_data(self) -> dict[str, str]:
        """Get the latest data from GTFS and GTFS relatime, depending refresh interval"""
        data = self.config_entry.data
        options = self.config_entry.options
        
        self._pygtfs = get_gtfs(
            self.hass, DEFAULT_PATH, data, False
        )
        previous_data = None if self.data is None else self.data.copy()

        if previous_data is not None and (datetime.datetime.strptime(previous_data["next_departure"]["gtfs_updated_at"],'%Y-%m-%dT%H:%M:%S.%f%z') + timedelta(minutes=options.get("refresh_interval", DEFAULT_REFRESH_INTERVAL))) >  dt_util.utcnow() + timedelta(seconds=1) :
            # do nothing awaiting refresh interval
            self._data = previous_data
 
        if previous_data is None or  (datetime.datetime.strptime(previous_data["next_departure"]["gtfs_updated_at"],'%Y-%m-%dT%H:%M:%S.%f%z') + timedelta(minutes=options.get("refresh_interval", DEFAULT_REFRESH_INTERVAL))) <  dt_util.utcnow() + timedelta(seconds=1):
            self._data = {
                "schedule": self._pygtfs,
                "origin": data["origin"].split(": ")[0],
                "destination": data["destination"].split(": ")[0],
                "offset": data["offset"],
                "include_tomorrow": data["include_tomorrow"],
                "gtfs_dir": DEFAULT_PATH,
                "name": data["name"],
            }
            
            check_index = await self.hass.async_add_executor_job(
                    check_datasource_index, self._pygtfs
                )

            try:
                self._data["next_departure"] = await self.hass.async_add_executor_job(
                    get_next_departure, self
                )
            except Exception as ex:  # pylint: disable=broad-except
                _LOGGER.error("Error getting gtfs data from generic helper: %s", ex)
                return None
            _LOGGER.debug("GTFS coordinator data from helper: %s", self._data["next_departure"]) 
        
        # collect and return rt attributes
        # STILL REQUIRES A SOLUTION IF TIMING OUT
        if "real_time" in options:
            if options["real_time"]:
                self._get_next_service = {}
                """Initialize the info object."""
                self._trip_update_url = options["trip_update_url"]
                self._vehicle_position_url = options["vehicle_position_url"]
                self._route_delimiter = "-"
                if CONF_API_KEY in options:
                    self._headers = {"Authorization": options[CONF_API_KEY]}
                elif CONF_X_API_KEY in options:
                    self._headers = {"x-api-key": options[CONF_X_API_KEY]}
                else:
                    self._headers = None
                self._headers = None
                self.info = {}
                self._route_id = self._data["next_departure"]["route_id"]
                self._stop_id = data["origin"].split(": ")[0]
                self._direction = data["direction"]
                self._relative = False
                try:
                    self._get_rt_route_statuses = await self.hass.async_add_executor_job(get_rt_route_statuses, self)
                    self._get_next_service = await self.hass.async_add_executor_job(get_next_services, self)
                    self._data["next_departure"]["next_departure_realtime_attr"] = self._get_next_service
                    self._data["next_departure"]["next_departure_realtime_attr"]["gtfs_rt_updated_at"] = dt_util.utcnow()
                except Exception as ex:  # pylint: disable=broad-except
                    _LOGGER.error("Error getting gtfs realtime data: %s", ex)
            else:
                _LOGGER.info("GTFS RT: RealTime = false, selected in entity options")            
        else:
            _LOGGER.debug("GTFS RT: RealTime not selected in entity options")
        return self._data

