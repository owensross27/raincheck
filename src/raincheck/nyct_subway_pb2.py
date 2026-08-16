"""NYCT subway GTFS-RT extension (nyct-subway.proto), compiled descriptor vendored from
nyct-gtfs 2.1.0 (MIT, Andrew Dickinson); rebuilt for protobuf >= 4.21 builder API.
Registers nyct_feed_header / nyct_trip_descriptor / nyct_stop_time_update on the
gtfs-realtime-bindings messages. Facts: vault/nyc-mta-bus-feeds-reference.md."""
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf.internal import builder as _builder
from google.transit import gtfs_realtime_pb2 as _gtfs  # noqa: F401  (loads gtfs-realtime.proto into the pool)

DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n\x11nyct-subway.proto\x1a\x13gtfs-realtime.proto\"b\n\x15TripReplacementPeriod\x12\x10\n\x08route_id\x18\x01 \x01(\t\x12\x37\n\x12replacement_period\x18\x02 \x01(\x0b\x32\x1b.transit_realtime.TimeRange\"f\n\x0eNyctFeedHeader\x12\x1b\n\x13nyct_subway_version\x18\x01 \x02(\t\x12\x37\n\x17trip_replacement_period\x18\x02 \x03(\x0b\x32\x16.TripReplacementPeriod\"\xa4\x01\n\x12NyctTripDescriptor\x12\x10\n\x08train_id\x18\x01 \x01(\t\x12\x13\n\x0bis_assigned\x18\x02 \x01(\x08\x12\x30\n\tdirection\x18\x03 \x01(\x0e\x32\x1d.NyctTripDescriptor.Direction\"5\n\tDirection\x12\t\n\x05NORTH\x10\x01\x12\x08\n\x04\x45\x41ST\x10\x02\x12\t\n\x05SOUTH\x10\x03\x12\x08\n\x04WEST\x10\x04\"C\n\x12NyctStopTimeUpdate\x12\x17\n\x0fscheduled_track\x18\x01 \x01(\t\x12\x14\n\x0c\x61\x63tual_track\x18\x02 \x01(\t:H\n\x10nyct_feed_header\x12\x1c.transit_realtime.FeedHeader\x18\xe9\x07 \x01(\x0b\x32\x0f.NyctFeedHeader:T\n\x14nyct_trip_descriptor\x12 .transit_realtime.TripDescriptor\x18\xe9\x07 \x01(\x0b\x32\x13.NyctTripDescriptor:`\n\x15nyct_stop_time_update\x12+.transit_realtime.TripUpdate.StopTimeUpdate\x18\xe9\x07 \x01(\x0b\x32\x13.NyctStopTimeUpdateB\x1d\n\x1b\x63om.google.transit.realtime')
_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, "nyct_subway_pb2", _globals)
